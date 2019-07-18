#!/usr/bin/env python3
import os
import re
import subprocess
import shlex

megaclipath = '/opt/MegaRAID/MegaCli/MegaCli64'


def mega_ctl(*args):
    """Wrapper around invoking the smartctl binary.

    Returns:
        (str) Data piped to stdout by the smartctl subprocess.
    """
    try:
        paras = [item for item in args]
        # ['ssh', '-l', 'root', '101.100.11.225', 'smartctl']
        res = subprocess.Popen(
            [megaclipath] + paras, stdout=subprocess.PIPE
        )
        sout, serr = res.communicate()
        return sout.decode('utf-8')
    except subprocess.CalledProcessError as e:
        return e.output.decode('utf-8')


def returnControllerNumber(output):
    for line in output:
        if re.match(r'^Controller Count.*$', line.strip()):
            return int(line.split(':')[1].strip().strip('.'))


def returnControllerModel(output):
    for line in output:
        if re.match(r'^Product Name.*$', line.strip()):
            return line.split(':')[1].strip()


def returnMemorySize(output):
    for line in output:
        if re.match(r'^Memory Size.*$', line.strip()):
            return line.split(':')[1].strip()


def returnFirmwareVersion(output):
    for line in output:
        if re.match(r'^FW Package Build.*$', line.strip()):
            return line.split(':')[1].strip()


def returnROCTemp(output):
    ROCtemp = ''
    for line in output:
        if re.match(r'^ROC temperature :.*$', line.strip()):
            tmpstr = line.split(':')[1].strip()
            ROCtemp = re.sub(' +.*$', '', tmpstr)
    if (ROCtemp != ''):
        return str(str(ROCtemp) + 'C')
    else:
        return str('N/A')


def returnBBUPresence(output):
    BBU = ''
    for line in output:
        if re.match(r'^BBU +:.*$', line.strip()):
            tmpstr = line.split(':')[1].strip()
            BBU = re.sub(' +.*$', '', tmpstr)
            break
    if (BBU != ''):
        return str(BBU)
    else:
        return str('N/A')


def returnBBUStatus(output):
    BBUStatus = ''
    for line in output:
        if re.match(r'^ *Battery Replacement required +:.*$', line.strip()):
            tmpstr = line.split(':')[1].strip()
            BBUStatus = re.sub(' +.*$', '', tmpstr)
            break
    if (BBUStatus == 'Yes'):
        return str('REPL')
    else:
        return str('Good')


output = mega_ctl('-adpCount', ' -NoLog').strip().split('\n')
controllernumber = returnControllerNumber(output)

print('-- Controller information --')
controllerid = 0
hbainfo = []

print("ID", "H/W Model", "RAM", "Temp", "BBU", "Firmware")


def returnHBAInfo(table, output, controllerid):
    controllermodel = returnControllerModel(output)
    controllerram = returnMemorySize(output)
    controllerrev = returnFirmwareVersion(output)
    controllertemp = returnROCTemp(output)
    controllerbbu = returnBBUPresence(output)
    if controllerbbu == 'Present':
        cmd = '-AdpBbuCmd -GetBbuStatus -a{controllerid} -NoLog'.format(controllerid=controllerid)
        output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
        controllerbbu = returnBBUStatus(output)

    if controllermodel != 'Unknown':
        table.append(['c' + str(controllerid), controllermodel, controllerram, str(controllertemp), str(controllerbbu),
                      str('FW: ' + controllerrev)])


while controllerid < controllernumber:
    cmd = '-AdpAllInfo -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    returnHBAInfo(hbainfo, output, controllerid)
    controllerid += 1

print('-- Array information --')


def returnArrayNumber(output):
    i = 0
    for line in output:
        if re.match(r'^(CacheCade )?Virtual Drive:.*$', line.strip()):
            i += 1
    return i


def returnArrayInfo(output, controllerid, arrayid, arrayindex):
    id = 'c' + str(controllerid) + 'u' + str(arrayid)
    operationlinennumber = False
    linenumber = 0
    targetid = ''
    raidlvl = ''
    size = ''
    state = 'N/A'
    strpsz = ''
    dskcache = 'N/A'
    properties = ''
    spandepth = 0
    diskperspan = 0
    cachecade_info = 'None'

    for line in output:
        if re.match(r'^(CacheCade )?Virtual Drive:.*(Target Id: [0-9]+).*$', line.strip()):
            # Extract the SCSI Target ID
            targetid = line.strip().split(':')[2].split(')')[0].strip()
        elif re.match(r'^RAID Level.*?:.*$', line.strip()):
            # Extract the primary raid type, decide on X0 RAID level later when we hit Span Depth
            raidlvl = int(line.strip().split(':')[1].split(',')[0].split('-')[1].strip())
        elif re.match(r'^Size.*?:.*$', line.strip()):
            # Size reported in MB
            if re.match(r'^.*MB$', line.strip().split(':')[1]):
                size = line.strip().split(':')[1].strip('MB').strip()
                if float(size) > 1000:
                    size = str(int(round((float(size) / 1000)))) + 'G'
                else:
                    size = str(int(round(float(size)))) + 'M'
            # Size reported in TB
            elif re.match(r'^.*TB$', line.strip().split(':')[1]):
                size = line.strip().split(':')[1].strip('TB').strip()
                size = str(int(round((float(size) * 1000)))) + 'G'
            # Size reported in GB (default)
            else:
                size = line.strip().split(':')[1].strip('GB').strip()
                size = str(int(round((float(size))))) + 'G'
        elif re.match(r'^Span Depth.*?:.*$', line.strip()):
            # If Span Depth is greater than 1 chances are we have a RAID 10, 50 or 60
            spandepth = line.strip().split(':')[1].strip()
        elif re.match(r'^State.*?:.*$', line.strip()):
            state = line.strip().split(':')[1].strip()
        elif re.match(r'^Strip Size.*?:.*$', line.strip()):
            strpsz = line.strip().split(':')[1].strip()
        elif re.match(r'^Number Of Drives per span.*:.*$', line.strip()):
            diskperspan = int(line.strip().split(':')[1].strip())
        elif re.match(r'^Current Cache Policy.*?:.*$', line.strip()):
            props = line.strip().split(':')[1].strip()
            if re.search('ReadAdaptive', props):
                properties += 'ADRA'
            if re.search('ReadAhead', props):
                properties += 'RA'
            if re.match('ReadAheadNone', props):
                properties += 'NORA'
            if re.search('WriteBack', props):
                properties += ',WB'
            if re.match('WriteThrough', props):
                properties += ',WT'
        elif re.match(r'^Disk Cache Policy.*?:.*$', line.strip()):
            props = line.strip().split(':')[1].strip()
            if re.search('Disabled', props):
                dskcache = 'Disabled'
            if re.search('Disk.s Default', props):
                dskcache = 'Default'
            if re.search('Enabled', props):
                dskcache = 'Enabled'
        elif re.match(r'^Ongoing Progresses.*?:.*$', line.strip()):
            operationlinennumber = linenumber
        elif re.match(r'Cache Cade Type\s*:.*$', line):
            cachecade_info = "Type : " + line.strip().split(':')[1].strip()
        elif re.match(r'^Target Id of the Associated LDs\s*:.*$', line):
            associated = []
            for array in line.split(':')[1].strip().split(','):
                if array.isdigit():
                    associated.append('c%du%d' % (controllerid, int(array)))
            if len(associated) >= 1:
                cachecade_info = "Associated : %s" % (', '.join(associated))
        linenumber += 1

    # If there was an ongoing operation, find the relevant line in the previous output
    if operationlinennumber:
        inprogress = str(output[operationlinennumber + 1])
        # some ugly output fix..
        str1 = inprogress.split(':')[0].strip()
        str2 = inprogress.split(':')[1].strip()
        inprogress = str1 + " : " + str2
    else:
        inprogress = 'None'

    # Compute the RAID level
    NestedLDTable[int(controllerid)][int(arrayindex)] = False
    if raidlvl == '':
        raidtype = str('N/A')
    else:
        if int(spandepth) >= 2:
            raidtype = str('RAID-' + str(raidlvl) + '0')
            NestedLDTable[controllerid][int(arrayindex)] = True
        else:
            if raidlvl == 1:
                if diskperspan > 2:
                    raidtype = str('RAID-10')
                    NestedLDTable[controllerid][int(arrayindex)] = True
                else:
                    raidtype = str('RAID-' + str(raidlvl))
            else:
                raidtype = str('RAID-' + str(raidlvl))
    return [id, raidtype, size, strpsz, properties, dskcache, state, targetid, cachecade_info, inprogress]


controllerid = 0
pcipath = ''
diskpath = ''

# Hardcode a max of 16 HBA and 128 LDs for now. LDTable must be initialized to
# accept populating list of LD's into each ctlr's list.
MaxNumHBA = 16
MaxNumLD = 128
LDTable = [[] * MaxNumHBA for i in range(MaxNumLD)]
NestedLDTable = [[False for i in range(MaxNumLD)] for j in range(MaxNumHBA)]

while controllerid < controllernumber:
    arrayindex = 0
    cmd = '-LDInfo -lall -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    arraynumber = returnArrayNumber(output)
    ldid, ldcount = 0, 0
    while ldcount < arraynumber:
        cmd = '-LDInfo -l{ldid} -a{controllerid} -NoLog'.format(ldid=ldid, controllerid=controllerid)
        output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
        for line in output:
            if re.match(r'^Adapter.*Virtual Drive .* Does not Exist', line.strip()):
                ldid += 1
            elif re.match(r'^(CacheCade )?Virtual Drive:', line.strip()):
                LDTable[controllerid].append(ldid)
                # NestedLDTable[controllerid][int(arrayindex)] = False
                ldcount += 1
                ldid += 1

    while arrayindex < arraynumber:
        ldid = LDTable[controllerid][arrayindex]
        cmd = '-LDInfo -l{ldid} -a{controllerid} -NoLog'.format(ldid=ldid, controllerid=controllerid)
        output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
        arrayinfo = returnArrayInfo(output, controllerid, ldid, arrayindex)
        arrayindex += 1
    controllerid += 1


def returnHBAPCIInfo(output):
    busprefix = '0000'
    busid = ''
    devid = ''
    functionid = ''
    pcipath = ''
    for line in output:
        if re.match(r'^Bus Number.*:.*$', line.strip()):
            busid = str(line.strip().split(':')[1].strip()).zfill(2)
        if re.match(r'^Device Number.*:.*$', line.strip()):
            devid = str(line.strip().split(':')[1].strip()).zfill(2)
        if re.match(r'^Function Number.*:.*$', line.strip()):
            functionid = str(line.strip().split(':')[1].strip()).zfill(1)
    if busid:
        pcipath = str(busprefix + ':' + busid + ':' + devid + '.' + functionid)
        return str(pcipath)
    else:
        return None


def returnArrayNumber(output):
    i = 0
    for line in output:
        if re.match(r'^(CacheCade )?Virtual Drive:.*$', line.strip()):
            i += 1
    return i


controllerid = 0
while controllerid < controllernumber:
    arrayindex = 0
    cmd = '-AdpGetPciInfo -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    pcipath = returnHBAPCIInfo(output)

    cmd = '-LDInfo -lall -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    arraynumber = returnArrayNumber(output)
    while arrayindex < arraynumber:
        ldid = LDTable[controllerid][arrayindex]
        cmd = '-LDInfo -l{ldid} -a{controllerid} -NoLog'.format(ldid=ldid, controllerid=controllerid)
        output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
        arrayinfo = returnArrayInfo(output, controllerid, ldid, arrayindex)

        if pcipath:
            diskprefix = str('/dev/disk/by-path/pci-' + pcipath + '-scsi-0:')
            # RAID disks are usually with a channel of '2', JBOD disks with a channel of '0'
            for j in range(1, 8):
                diskpath = diskprefix + str(j) + ':' + str(arrayinfo[7]) + ':0'
                if os.path.exists(diskpath):
                    arrayinfo[7] = os.path.realpath(diskpath)
                    break
        else:
            arrayinfo[7] = 'N/A'

        arrayindex += 1
    controllerid += 1

print('-- Disk information --')

controllerid = 0
totaldrivenumber = 0


def returnTotalDriveNumber(output):
    for line in output:
        if re.match(r'Number of Physical Drives on Adapter.*$', line.strip()):
            return int(line.split(':')[1].strip())


def returnRebuildProgress(output):
    percent = 0
    for line in output:
        if re.match(r'^Rebuild Progress on Device at Enclosure.*, Slot .* Completed ', line.strip()):
            tmpstr = line.split('Completed')[1].strip()
            percent = int(tmpstr.split('%')[0].strip())
    return percent


def returnDiskInfo(output, controllerid):
    arrayid = False
    arrayindex = -1
    sarrayid = 'Unknown'
    diskid = False
    oldenclid = False
    enclid = False
    spanid = False
    slotid = False
    lsidid = 'Unknown'
    table = []
    fstate = 'Offline'
    model = 'Unknown'
    speed = 'Unknown'
    mtype = 'Unknown'
    dsize = 'Unknown'
    for line in output:
        if re.match(r'^Span: [0-9]+ - Number of PDs:', line.strip()):
            spanid = line.split(':')[1].strip()
            spanid = re.sub(' - Number of PDs.*', '', spanid)
        elif re.match(r'Enclosure Device ID: .*$', line.strip()):
            # We match here early in the analysis so reset the vars if this is a new disk we're reading..
            oldenclid = enclid
            enclid = line.split(':')[1].strip().replace("N/A", "")
            if oldenclid != False:
                fstate = 'Offline'
                model = 'Unknown'
                speed = 'Unknown'
                slotid = False
                lsidid = 'Unknown'
        elif re.match(r'^Coerced Size: ', line.strip()):
            dsize = line.split(':')[1].strip()
            dsize = re.sub(" \[.*\.*$", '', dsize)
            dsize = re.sub('[0-9][0-9] GB', ' Gb', dsize)
        elif re.match(r'^(CacheCade )?Virtual (Disk|Drive): [0-9]+.*$', line.strip()):
            arrayindex += 1
            arrayid = line.split('(')[0].split(':')[1].strip()
        elif re.match(r'^Drive.s posi*tion: DiskGroup: [0-9]+,.*$', line.strip()):
            notarrayid = line.split(',')[1].split(':')[1].strip()
        elif re.match(r'PD: [0-9]+ Information.*$', line.strip()):
            diskid = line.split()[1].strip()
        elif re.match(r'^Device Id: .*$', line.strip()):
            lsidid = line.split(':')[1].strip()
        elif re.match(r'Slot Number: .*$', line.strip()):
            slotid = line.split(':')[1].strip()
        elif re.match(r'Firmware state: .*$', line.strip()):
            fstate = line.split(':')[1].strip()
            subfstate = re.sub('\(.*', '', fstate)
        elif re.match(r'Inquiry Data: .*$', line.strip()):
            model = line.split(':')[1].strip()
            model = re.sub(' +', ' ', model)
            # Sub code
            manuf = re.sub(' .*', '', model)
            dtype = re.sub(manuf + ' ', '', model)
            dtype = re.sub(' .*', '', dtype)
            hwserial = re.sub('.*' + dtype + ' *', '', model)
        elif re.match(r'^Media Type: .*$', line.strip()):
            mtype = line.split(':')[1].strip()
            if mtype == 'Hard Disk Device':
                mtype = 'HDD'
            else:
                if mtype == 'Solid State Device':
                    mtype = 'SSD'
                else:
                    mtype = 'N/A'
        elif re.match(r'Device Speed: .*$', line.strip()):
            speed = line.split(':')[1].strip()
        elif re.match(r'Drive Temperature :.*$', line.strip()):
            # Drive temp is amongst the last few lines matched, decide here if we add information to the table..
            temp = line.split(':')[1].strip()
            temp = re.sub(' \(.*\)', '', temp)
            if model != 'Unknown':
                if subfstate == 'Rebuild':
                    cmd = 'pdrbld -showprog -physdrv\[{enclid}:{slotid}\] -a{controllerid} -NoLog'.format(
                        enclid=enclid, slotid=slotid, controllerid=controllerid)
                    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
                    percent = returnRebuildProgress(output)
                    fstate = str('Rebuilding (%d%%)' % (percent))

                if (NestedLDTable[controllerid][int(arrayindex)] == True) and (spanid != False):
                    sarrayid = str(arrayid) + "s" + spanid
                else:
                    sarrayid = str(arrayid)
                table.append([sarrayid, str(diskid), mtype, model, dsize, fstate, speed, temp, enclid, slotid, lsidid])
    return table


def AddDisk(mytable, disk):
    if mytable.has_key(disk):
        return False
    else:
        mytable[disk] = True
        return True


while controllerid < controllernumber:
    cmd = '-PDGetNum -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    totaldrivenumber += returnTotalDriveNumber(output)
    controllerid += 1

controllerid = 0
NagiosBadDisks = {}
NagiosGoodDisks = {}
nagiosgooddisk = 0
nagiosbaddisk = 0

while controllerid < controllernumber:
    arrayid = 0
    cmd = '-LDInfo -lall -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    arraynumber = returnArrayNumber(output)
    cmd = '-LdPdInfo -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    arraydisk = returnDiskInfo(output, controllerid)
    for array in arraydisk:
        diskname = str(controllerid) + array[8] + array[9]
        if re.match("|".join(['^Online$', '^Online, Spun Up$', '^Rebuilding \(.*']), array[5]):
            if AddDisk(NagiosGoodDisks, diskname):
                nagiosgooddisk += 1
        else:
            bad = True
            if AddDisk(NagiosBadDisks, diskname):
                nagiosbaddisk += 1
    controllerid += 1

controllerid = 0
totalconfdrivenumber = 0
totalunconfdrivenumber = 0
totaldrivenumber = 0
ConfDisks = {}


def returnConfDriveNumber(controllerid, output):
    # Count the configured drives
    confdrives = 0
    enclid = 'N/A'
    slotid = 'N/A'
    for line in output:

        if re.match(r'Enclosure Device ID: .*$', line.strip()):
            # We match here early in the analysis so reset the vars if this is a new disk we're reading..
            enclid = line.split(':')[1].strip()
        elif re.match(r'Slot Number: .*$', line.strip()):
            slotid = line.split(':')[1].strip()
            if AddDisk(ConfDisks, str(controllerid) + enclid + slotid):
                confdrives += 1
    return int(confdrives)


def returnUnConfDriveNumber(output):
    # Count the un-configured/Hotspare drives
    unconfdrives = 0
    for line in output:
        if re.match(r'^Firmware state: Unconfigured.*$', line.strip()):
            unconfdrives += 1
        elif re.match(r'^Firmware state: Hotspare.*$', line.strip()):
            unconfdrives += 1
    return int(unconfdrives)


while controllerid < controllernumber:
    cmd = '-LdPdInfo -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    totalconfdrivenumber += returnConfDriveNumber(controllerid, output)

    cmd = '-PDGetNum -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    totaldrivenumber += returnTotalDriveNumber(output)

    cmd = '-PDList -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    # Sometimes a drive will be reconfiguring without any info on that it is going through a rebuild process. This
    # happens when expanding an R{5,6,50,60} array, for example. In that case, totaldrivenumber will still be greater
    # than totalconfdrivenumber while returnUnConfDriveNumber(output) will be zero. The math below attempts to solve
    # this.
    totalunconfdrivenumber += max(returnUnConfDriveNumber(output), totaldrivenumber - totalconfdrivenumber)
    controllerid += 1

print('-- Unconfigured Disk information --')
controllerid = 0
pcipath = ''


def returnUnconfDiskInfo(output):
    arrayid = False
    diskid = False
    enclid = False
    slotid = False
    table = []
    fstate = 'Offline'
    model = 'Unknown'
    speed = 'Unknown'
    mtype = 'Unknown'
    dsize = 'Unknown'
    ospath = 'N/A'
    for line in output:
        if re.match(r'Enclosure Device ID: .*$', line.strip()):
            # We match here early in the analysis so reset the vars if this is a new disk we're reading..
            oldenclid = enclid
            enclid = line.split(':')[1].strip().replace("N/A", "")
            if oldenclid != False:
                arrayid = False
                fstate = 'Offline'
                model = 'Unknown'
                speed = 'Unknown'
                slotid = False

        elif re.match(r'^Coerced Size: ', line.strip()):
            dsize = line.split(':')[1].strip()
            dsize = re.sub(' \[.*\.*$', '', dsize)
            dsize = re.sub('[0-9][0-9] GB', ' Gb', dsize)
        elif re.match(r'^Drive.s posi*tion: DiskGroup: [0-9]+,.*$', line.strip()):
            arrayid = line.split(',')[1].split(':')[1].strip()
        elif re.match(r'^Device Id: [0-9]+.*$', line.strip()):
            diskid = line.split(':')[1].strip()
        elif re.match(r'Slot Number: .*$', line.strip()):
            slotid = line.split(':')[1].strip()
        elif re.match(r'Firmware state: .*$', line.strip()):
            fstate = line.split(':')[1].strip()
        elif re.match(r'Inquiry Data: .*$', line.strip()):
            model = line.split(':')[1].strip()
            model = re.sub(' +', ' ', model)
            manuf = re.sub(' .*', '', model)
            dtype = re.sub(manuf + ' ', '', model)
            dtype = re.sub(' .*', '', dtype)
            hwserial = re.sub('.*' + dtype + ' *', '', model)
        elif re.match(r'^Media Type: .*$', line.strip()):
            mtype = line.split(':')[1].strip()
            if mtype == 'Hard Disk Device':
                mtype = 'HDD'
            else:
                if mtype == 'Solid State Device':
                    mtype = 'SSD'
                else:
                    mtype = 'N/A'
        elif re.match(r'Device Speed: .*$', line.strip()):
            speed = line.split(':')[1].strip()
        elif re.match(r'Drive Temperature :.*$', line.strip()):
            # Drive temp is amongst the last few lines matched, decide here if we add information to the table..
            temp = line.split(':')[1].strip()
            temp = re.sub('\(.*\)', '', temp)
            if not arrayid:
                table.append([mtype, model, dsize, fstate, speed, temp, enclid, slotid, diskid, ospath])
    return table


while controllerid < controllernumber:
    arrayid = 0
    cmd = '-LDInfo -lall -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    arraynumber = returnArrayNumber(output)
    cmd = '-AdpGetPciInfo -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    pcipath = returnHBAPCIInfo(output)
    cmd = '-PDList -a{controllerid} -NoLog'.format(controllerid=controllerid)
    output = mega_ctl(*shlex.split(cmd, comments=True)).strip().split('\n')
    arraydisk = returnUnconfDiskInfo(output)
    for array in arraydisk:
        if array[3] in ['Online', 'Unconfigured(good), Spun Up', 'Unconfigured(good), Spun down', 'JBOD',
                        'Hotspare, Spun Up', 'Hotspare, Spun down', 'Online, Spun Up']:
            nagiosgooddisk += 1
        else:
            bad = True
            nagiosbaddisk += 1

        # JBOD disks has a real device path and are not masked. Try to find a device name here, if possible.
        if pcipath:
            if array[3] in ['JBOD']:
                diskprefix = str('/dev/disk/by-path/pci-' + pcipath + '-scsi-0:0:')
                # RAID disks are usually with a channel of '2', JBOD disks with a channel of '0'
                diskpath = diskprefix + str(array[8]) + ':0'
                if os.path.exists(diskpath):
                    array[9] = os.path.realpath(diskpath)
                else:
                    array[9] = 'N/A'
