#!/usr/bin/env python
import sys
import pybedtools
import pysam
import os
import subprocess
from uuid import uuid4
from re import sub
from itertools import izip

import gzip
import shutil
import traceback
import time
import multiprocessing
from multiprocessing import Pool
from contextlib import closing
from pathos.multiprocessing import ProcessingPool 
import signal
import itertools
import ntpath
import fnmatch

from threading import Thread
from helpers import handlers as handle
from helpers import parameters as params

configReader = params.GetConfigReader()
#modify later
java_path="/mnt/work1/software/java/8/jdk1.8.0_45/bin/java"
beagle_jar="/mnt/work1/users/pughlab/projects/Benchmarking/Beagle/beagle.09Nov15.d2a.jar"
samtool_path = "/cluster/tools/software/samtools/0.1.18/samtools"


def gzipFile(filename):
    with open(filename, 'rb') as f_in, gzip.open(filename+'.gz', 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)

def thinVCF(invcf, outvcf):
   command = " ".join(["vcftools --vcf", invcf, "--thin 50 --out", outvcf,  "--recode"])
   print("thin VCF called with command: "+command )
   runCommand(command)

def extractPairedReadfromROI(inbamfn, bedfn, outbamfn, flag = "either"):
    command = " ".join(["bedtools pairtobed -abam", inbamfn,"-b",bedfn, "-type", flag,">", outbamfn, "2> bedtool.log"])
    runCommand(command)
    
def extractBAMfromROI_All(inbamfn, bedfn, outbamfn):
    command = " ".join(["samtools view -b -L", bedfn, inbamfn, ">",outbamfn])
    runCommand(command)

def dedupBam(inbamfn, outbamfn):
    command = " ".join([samtool_path, "rmdup", inbamfn, outbamfn])
    runCommand(command)

def runCommand(cmd):
    try:
        thread = Thread(group=None, target=lambda:os.system(cmd))
        thread.run()
        if not thread.is_alive():
            return 0
        else:
            return 1
    except OSError as e:
        #logger.debug("Execution failed %s", e)
        sys.exit(1)

#phase unphased VCF into Hap1 and Hap2 phased alleles using BEAGLE
def phaseVCF(vcfpath, phasevcfpath):
    print (" ___ phasing vcf file ___ "  )
    if(not vcfpath.endswith('.vcf.gz')):
        gzipFile(vcfpath)
        vcfpath = vcfpath+'.gz'
    
    path, vcffn = os.path.split(vcfpath)
    path2, vcffn2 = os.path.split(phasevcfpath)
    phasevcffn = sub('.vcf.gz$', '_phased', vcffn)
    command = " ".join([java_path,"-Xmx4g -jar", beagle_jar, "gt="+vcfpath, "out="+"/".join([path2, phasevcffn])])
    runCommand(command)
    return phasevcffn

def getVCFHaplotypes(phasedvcf, hap1, hap2):
    out_hap1 = open(hap1, 'w')
    out_hap2 = open(hap2, 'w')
    
    if(phasedvcf.endswith('.vcf.gz')):
        vcfh = gzip.GzipFile(phasedvcf, 'rb')
          
        for line in vcfh:
            c = line.strip('\n').split("\t")
            if (len(c) == 10 ):
                if(c[9] == '0|1:1'):
                    out_hap1.write(line)
                    continue
                elif(c[9] == '1|0:1'):
                     out_hap2.write(line)
                     continue
                
            elif(line.startswith('#')):
                out_hap1.write(line)
                out_hap2.write(line)
                continue
        
    out_hap1.close()
    out_hap2.close()
   

def convertvcftobed(vcf, bed):
    
    vcfh = open(vcf, 'r')
    bedh = open(bed, 'w')
    
    for line in vcfh:
        c = line.strip('\n').split("\t")
        
        if (not line.startswith('#') and len(c) >= 5 and (len(c[3])+len(c[4]) == 2)):
           start = int(c[1]) - 1
           bedh.write(c[0]+'\t'+str(start) +'\t'+ str(c[1])+'\t' + str(c[3]) + '\t' + str(c[4]) + '\n') #chr start stop ref alt
        
    bedh.close()
    

#report exon bedfiles that are within the defined CNV region
def findExonsinCNVregion(cnvpath, exonpath, intersectfile, wa=False):
    cwd = os.path.dirname(__file__)
    cnvcompletepath = os.path.realpath(cnvpath.format(cwd))
    exoncompletepath = os.path.realpath(exonpath.format(cwd))
      
    cnvfile = pybedtools.example_bedtool(cnvcompletepath)
    exonfile = pybedtools.example_bedtool(exoncompletepath)
    
    f = open(intersectfile, 'w')
    if(wa == False):
        print >> f, exonfile.intersect(cnvfile,u=True)
    elif(wa==True):
        print >> f, exonfile.intersect(cnvfile,u=True,wa=True)
            
    f.close()
    return intersectfile

def subtractBeds(bedfn1, bedfn2, diffn):
    cwd = os.path.dirname(__file__)
    bed1fullpath = os.path.realpath(bedfn1.format(cwd))
    bed2fullpath = os.path.realpath(bedfn2.format(cwd))
      
    bed1 = pybedtools.example_bedtool(bed1fullpath)
    bed2 = pybedtools.example_bedtool(bed2fullpath)
    
    print (bed2fullpath +"\n" +bed2fullpath +"\n"+ diffn)
    f = open(diffn, 'w')
    print >> f, bed1.subtract(bed2, A = True)
    f.close()

def bamDiff(bamfn1, bamfn2, path):
    command = " ".join(["bam diff", "--in1", bamfn1, "--in2", bamfn2, "--out" ,"/".join([path,"diff.bam"])]) 
    runCommand(command ) 


def intersectBed(bed1fn, bed2fn, intersectfile, wa=False):
    cwd = os.path.dirname(__file__)
    
    bed1fncompletepath = os.path.realpath(bed1fn.format(cwd))
    bed2fncompletepath = os.path.realpath(bed2fn.format(cwd))
      
    bed1 = pybedtools.example_bedtool(bed1fncompletepath)
    bed2 = pybedtools.example_bedtool(bed2fncompletepath)
    
    f = open(intersectfile, 'w')
    if(wa == False):
        print("intersect bed called with wa=False")
        print >> f, bed1.intersect(bed2,u=True)
    elif(wa==True):
        print("intersect bed called with wa=True")
        print >> f, bed1.intersect(bed2,u=True,wa=True)
            
    f.close()
    return intersectfile

def call_subprocess(cmd):
    try:
        proc = subprocess.Popen(cmd, shell=False)
        out, err = proc.communicate()
    except:    
        logger.exception("Exception in call_subprocess " , sys.exc_info()[0])
        return
    
    
def renamereads(inbamfn, outbamfn):
    
    inbam = pysam.Samfile(inbamfn, 'rb')
    outbam = pysam.Samfile(outbamfn, 'wb', template=inbam)

    paired = {}

    n = 0
    p = 0
    u = 0
    w = 0
    m = 0
    
    for read in inbam.fetch(until_eof=True):
        n += 1
        if read.is_paired:
            p += 1
            if read.qname in paired:
                uuid = paired[read.qname]
                del paired[read.qname]
                read.qname = uuid
                outbam.write(read)
                w += 1
                m += 1
            else:
                newname = str(uuid4())
                paired[read.qname] = newname
                read.qname = newname
                outbam.write(read)
                w += 1
        else:
            u += 1
            read.qname = str(uuid4())
            outbam.write(read)
            w += 1

    outbam.close()
    inbam.close()


def subsample(bamfn1, bamfn2, samplingrate = 0.5):
    command = " ".join(["samtools view -s", samplingrate ,"-b", bamfn1, ">", bamfn2])
    runCommand(command)
  
def sortByName(inbamfn, outbamfn):
    command = " ".join(["sambamba sort -n", inbamfn, "-o", outbamfn])
    print(command)
    runCommand(command)
    
def sortIndexBam(inbamfn, outbamfn):
    command = " ".join(["sambamba sort", inbamfn, "-o", outbamfn])
    command2 = " ".join(["sambamba index", outbamfn])
    
    runCommand(command)
    runCommand(command2)

def sortBam(inbamfn, outbamfn):
    command = " ".join(["sambamba sort", inbamfn, "-o", outbamfn])
    runCommand(command)
  
def getProperPairs(inbamfn, outbamfn):
    command = " ".join(["samtools view -u -h -f 0x0003", inbamfn ,">", outbamfn])
    runCommand(command)  
    

def splitBed(bedfn, event):
    path, filename = os.path.split(bedfn)
    command=  "".join(["""awk '($1 ~ "chr"){print $0 >> """ ,'"{}"'.format(event), """$1".bed"}' """, bedfn])
    os.chdir(path)
    runCommand(command)
 
def generatePurities(purity):
    
    try:
         if not terminating.is_set():
            purityDir = createDirectory("/".join([finalbams_hap, str(purity)]))
            os.chdir(purityDir)
            subsample
            
    
    except (KeyboardInterrupt):
    
        logger.error('Exception Crtl+C pressed in the child process  in generation purities' )
        terminating.set()
        return
    
    except:    
    
        logger.exception("message")
        terminating.set()
        return
    return          

def merge_bams(bamfn1, bamfn2, mergefn):
    command = " ".join(["sambamba merge", mergefn, bamfn1, bamfn2 ])
    runCommand(command)

def mergeSortBamFiles(mergedBamfn, finalbamdir):
    command = ""
    os.chdir(finalbamdir)
    matches = []
    
    for root,dirnames, filenames in os.walk(finalbamdir):
        for filename in fnmatch.filter(filenames, '*.bam'):
            
            path = os.path.join(root, filename)
            if os.path.islink(path):
                path = os.path.realpath(path)
                
            if (not matches.__contains__(path)):
                matches.append(path)
                command = " ".join([path, command])
            
    command2 = " ".join(["sambamba merge", mergedBamfn, command ])
    runCommand(command2)
    
def getMeanSTD(inbam):
    """ awk '{ if ($9 > 0) { N+=1; S+=$9; S2+=$9*$9 }} END { M=S/N; print "n="N", mean="M", stdev="sqrt ((S2-M*M*N)/(N-1))}' """
    command = " ".join([awk, inbam])
    runCommand(command )


def splitPairs(inbamfn):
    pair1fn =  sub('.bam$', '_read1.bam', inbamfn)
    pair2fn =  sub('.bam$', '_read2.bam', inbamfn)
    command1 = " ".join(["samtools view -u -h -f 0x0043", inbamfn, ">", pair1fn])
    command2 = " ".join(["samtools view -u -h -f 0x0083", inbamfn, ">", pair2fn])
    runCommand(command1)
    runCommand(command2)

def getStrands(inbamfn):
    outbamfn_forward =  sub('.bam$', '_forward.bam', inbamfn)
    outbamfn_reverse =  sub('.bam$', '_reverse.bam', inbamfn)
    command1 = " ".join(["samtools view -F 0x10", inbamfn, ">",outbamfn_forward])
    command2 = " ".join(["samtools view -f 0x10", inbamfn, ">",outbamfn_reverse])    
    runCommand(command1)
    runCommand(command2)
    
    
def countReads(inbamfn):
    cmd = " ".join(["samtools view", inbamfn, "|wc -l"])
    out,err= subprocess.Popen(cmd, 
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.PIPE, 
                            stdin=subprocess.PIPE, shell=True).communicate()
    return "".join(out.split())
 
def splitPairAndStrands(inbamfn):
    read1_strand1sortfn =  sub('.bam$', '.read1_pos.bam', inbamfn)
    read1_strand2sortfn =  sub('.bam$', '.read1_neg.bam', inbamfn)
    read2_strand1sortfn =  sub('.bam$', '.read2_pos.bam', inbamfn)
    read2_strand2sortfn =  sub('.bam$', '.read2_neg.bam', inbamfn)
    
    #command1 = " ".join(["samtools view -u -h -f 0x0063", inbamfn, ">", inbamfn+'R1S1.bam',";samtools sort", inbamfn+'R1S1.bam',read1_strand1sortfn])
    #command2 = " ".join(["samtools view -u -h -f 0x0053", inbamfn, ">", inbamfn+'R1S2.bam',";samtools sort", inbamfn+'R1S2.bam',read1_strand2sortfn])
    #command3 = " ".join(["samtools view -u -h -f 0x0093", inbamfn, ">", inbamfn+'R2S1.bam',";samtools sort", inbamfn+'R2S1.bam',read2_strand1sortfn])
    #command4 = " ".join(["samtools view -u -h -f 0x00A3", inbamfn, ">", inbamfn+'R2S2.bam',";samtools sort", inbamfn+'R2S2.bam',read2_strand2sortfn])
    
    command1 = " ".join(["samtools view -u -h -f 0x0063", inbamfn, ">", read1_strand1sortfn])
    command2 = " ".join(["samtools view -u -h -f 0x0053", inbamfn, ">", read1_strand2sortfn])
    command3 = " ".join(["samtools view -u -h -f 0x0093", inbamfn, ">", read2_strand1sortfn])
    command4 = " ".join(["samtools view -u -h -f 0x00A3", inbamfn, ">", read2_strand2sortfn])
    

    runCommand(command1)
    runCommand(command2)
    runCommand(command3)
    runCommand(command4)
    #os.remove(inbamfn+'R1S1.bam')
    #os.remove(inbamfn+'R1S2.bam')
    #os.remove(inbamfn+'R2S1.bam')
    #os.remove(inbamfn+'R2S2.bam')
 
def extract_proper_paired_reads(inbamfn):
    properfn = sub('.bam$', '_proper.bam', inbamfn)
    command = " ".join(["samtools view -f 0x03 -bSq 30", inbamfn, ">", properfn])
    runCommand(command)
    os.remove(inbamfn)
    
def createHaplotypes(hetsnp_orig_bed, hetsnp_hap1_bed ):
    try:
        inbedh = open(hetsnp_orig_bed, 'r')
        inbedh2 = open(hetsnp_hap1_bed, 'r')  
        for line in inbedh:
            c = line.strip('\n').split("\t")
            c2 = ""
            
            while (c2 != c):
                 c2 = inbedh2.readline.strip('\n').split("\t")
                 outbedh.write(c2 +'\t'+'hap1' +'\n')
            
            outbedh.write(c2 +'\t'+'hap2' +'\n')
            
        outbedh.close()
    except:
        print('exception')
   
#chr 21 and 22 for test, change it to 1
def create_chr_event_list():
    chrom_event= []
    for c in range(1,23):
        for e in ['gain','loss']:
            chev = "_".join(['chr'+str(c), e])
            chrom_event.append(chev)
    return chrom_event

def create_chr_bam_list():
    chrom_event= []
    for c in range(1,23):
        for e in ['nonhet','mutated']:
            chev = "_".join(['chr'+str(c), e])
            chrom_event.append(chev)
    return chrom_event






