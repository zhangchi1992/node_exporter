package exporter

import (
	"bufio"
	"fmt"
	"github.com/prometheus/client_golang/prometheus"
	"io"
	"net"
	"regexp"
	"strconv"
	"strings"
)

const (
	muninAddress = "127.0.0.1:4949"
	muninProto   = "tcp"
)

var muninBanner = regexp.MustCompile(`# munin node at (.*)`)

type muninCollector struct {
	name           string
	hostname       string
	gaugePerMetric map[string]prometheus.Gauge
	config         config
	registry       prometheus.Registry
	connection     net.Conn
}

// Takes a config struct and prometheus registry and returns a new Collector scraping munin.
func NewMuninCollector(config config, registry prometheus.Registry) (c muninCollector, err error) {
	c = muninCollector{
		name:           "munin_collector",
		config:         config,
		registry:       registry,
		gaugePerMetric: make(map[string]prometheus.Gauge),
	}

	return c, err
}

func (c *muninCollector) Name() string { return c.name }

func (c *muninCollector) connect() (err error) {
	c.connection, err = net.Dial(muninProto, muninAddress)
	if err != nil {
		return err
	}
	debug(c.Name(), "Connected.")

	reader := bufio.NewReader(c.connection)
	head, err := reader.ReadString('\n')
	if err != nil {
		return err
	}

	matches := muninBanner.FindStringSubmatch(head)
	if len(matches) != 2 { // expect: # munin node at <hostname>
		return fmt.Errorf("Unexpected line: %s", head)
	}
	c.hostname = matches[1]
	debug(c.Name(), "Found hostname: %s", c.hostname)
	return err
}

func (c *muninCollector) muninCommand(cmd string) (reader *bufio.Reader, err error) {
	if err := c.connect(); err != nil {
		return reader, fmt.Errorf("Couldn't connect to munin: %s", err)
	}
	reader = bufio.NewReader(c.connection)

	fmt.Fprintf(c.connection, cmd+"\n")

	_, err = reader.Peek(1)
	switch err {
	case io.EOF:
		debug(c.Name(), "not connected anymore, closing connection and reconnect.")
		c.connection.Close()
		err = c.connect()
		if err != nil {
			return reader, fmt.Errorf("Couldn't connect to %s: %s", muninAddress)
		}
		return c.muninCommand(cmd)
	case nil: //no error
		break
	default:
		return reader, fmt.Errorf("Unexpected error: %s", err)
	}

	return reader, err
}

func (c *muninCollector) muninList() (items []string, err error) {
	munin, err := c.muninCommand("list")
	if err != nil {
		return items, fmt.Errorf("Couldn't get list: %s", err)
	}

	response, err := munin.ReadString('\n') // we are only interested in the first line
	if err != nil {
		return items, fmt.Errorf("Couldn't read response: %s", err)
	}

	if response[0] == '#' { // # not expected here
		return items, fmt.Errorf("Error getting items: %s", response)
	}
	items = strings.Fields(strings.TrimRight(response, "\n"))
	return items, err
}

func (c *muninCollector) getGraphConfig(name string) (config map[string]map[string]string, graphConfig map[string]string, err error) {
	graphConfig = make(map[string]string)
	config = make(map[string]map[string]string)

	resp, err := c.muninCommand("config " + name)
	if err != nil {
		return config, graphConfig, fmt.Errorf("Couldn't get config for %s: %s", name, err)
	}

	for {
		line, err := resp.ReadString('\n')
		if err == io.EOF {
			debug(c.Name(), "EOF, retrying")
			return c.getGraphConfig(name)
		}
		debug(c.Name(), "config line: %s", line)
		if err != nil {
			return nil, nil, err
		}
		if line == ".\n" { // munin end marker
			break
		}
		if line[0] == '#' { // here it's just a comment, so ignore it
			continue
		}
		parts := strings.Fields(line)
		if len(parts) < 2 {
			return nil, nil, fmt.Errorf("Line unexpected: %s", line)
		}
		key, value := parts[0], strings.TrimRight(strings.Join(parts[1:], " "), "\n")
		debug(c.Name(), "key: %s, val: %s", key, value)

		key_parts := strings.Split(key, ".")
		if len(key_parts) > 1 { // it's a metric config (metric.label etc)
			debug(c.Name(), "its a metric config, existing config for %s: %s", key_parts[0], config[key_parts[0]])
			if _, ok := config[key_parts[0]]; !ok {
				config[key_parts[0]] = make(map[string]string)
			}
			debug(c.Name(), "config[%s][%s] = %s", key_parts[0], key_parts[1], value)
			config[key_parts[0]][key_parts[1]] = value
		} else {
			debug(c.Name(), "graph[%s] = %s", key_parts[0], value)
			graphConfig[key_parts[0]] = value
		}
	}
	return config, graphConfig, err
}

func (c *muninCollector) metricName(graph, metric string) string {
	return strings.Replace(graph+"-"+metric, ".", "_", -1)
}

func (c *muninCollector) Update() (updates int, err error) {
	graphs, err := c.muninList()
	if err != nil {
		return updates, fmt.Errorf("Couldn't get graph list: %s", err)
	}

	for _, graph := range graphs {
		debug(c.Name(), "fetching graph %s", graph)
		munin, err := c.muninCommand("fetch " + graph)
		if err != nil {
			return updates, err
		}

		for {
			line, err := munin.ReadString('\n')
			debug(c.Name(), "read: %s", line)
			line = strings.TrimRight(line, "\n")
			if err == io.EOF {
				debug(c.Name(), "unexpected EOF, retrying")
				return c.Update()
			}
			if err != nil {
				return updates, err
			}
			if len(line) == 1 && line[0] == '.' {
				break // end of list
			}

			parts := strings.Fields(line)
			metricParts := strings.Split(parts[0], ".")
			if len(metricParts) != 2 {
				debug(c.Name(), "unexpected line: %s", line)
				continue
			}
			if metricParts[1] != "value" {
				continue
			}
			metric := metricParts[0]

			value_s := strings.Join(parts[1:], " ")

			gauge, err := c.gaugeFor(graph, metric) // reference to existing or new metrics
			if err != nil {
				debug(c.Name(), "%s", err)
				continue
			}

			value, err := strconv.ParseFloat(value_s, 64)
			if err != nil {
				debug(c.Name(), "Couldn't parse value in line %s, malformed?", line)
				continue
			}

			labels := map[string]string{
				"collector": "munin",
				"hostname":  c.hostname,
			}
			debug(c.Name(), "Set %s/%s{%s}: %f\n", graph, metric, labels, value)
			gauge.Set(labels, value)
			updates++
		}
	}
	return updates, err
}

func (c *muninCollector) gaugeFor(graph, metric string) (prometheus.Gauge, error) {
	metricName := c.metricName(graph, metric)
	debug(c.Name(), "Is '%s' already registered?", metricName)

	gauge, ok := c.gaugePerMetric[metricName]
	if ok {
		return gauge, nil
	}

	configs, graphConfig, err := c.getGraphConfig(graph)
	if err != nil {
		return nil, fmt.Errorf("Couldn't get config for graph %s: %s", graph, err)
	}
	debug(c.Name(), "configs: %s, graphConfig: %s", configs, graphConfig)

	for metric, config := range configs {
		metricName := c.metricName(graph, metric)
		desc := graphConfig["graph_title"] + ": " + config["label"]
		if config["info"] != "" {
			desc = desc + ", " + config["info"]
		}
		gauge := prometheus.NewGauge()
		debug(c.Name(), "Register %s: %s", metricName, desc)
		c.gaugePerMetric[metricName] = gauge
		c.registry.Register(metricName, desc, prometheus.NilLabels, gauge)
	}

	gauge, ok = c.gaugePerMetric[metricName]
	if !ok {
		return nil, fmt.Errorf("metric %s (%s) not found in %s graph", metricName, metric, graph)
	}
	return c.gaugePerMetric[metricName], nil
}
