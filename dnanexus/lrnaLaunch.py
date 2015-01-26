#!/usr/bin/env python
import argparse
import os
import sys
#import subprocess
#from datetime import datetime
#import json

import dxpy
import dxencode as dxencode
#from dxencode import dxencode as dxencode
import json

# NOTES: This command-line utility will run the long RNA-seq pipeline for a single replicate
#      - All results will be written to a folder /lrna/<expId>/rep<#>.
#      - If any results are already in that directory, then the steps that created those results
#        will not be rerun.
#      - If any jobs for the experiment and replicate are already running, nothing new will be
#        launched.
#      - Most of the code is generic and found in dxencode.  It relies upon hard-coded JSON below.
#        Tokens are used to abstract dx.app input/outout file names to avoid collisions.
#        - STEP_ORDER is the list of steps in the pipeline
#        - STEPS contains step definitions and enforces dependencies by input file tokens matching
#          to result file tokens of earlier steps.
#        - FILE_GLOBS is needed for locating result files from prior runs.

GENOMES_SUPPORTED = ['hg19', 'mm10']
GENOME_DEFAULT = 'hg19'
''' This the default Genome that long RNA-seq experiments are mapped to.'''

ANNO_DEFAULTS = {'hg19': 'v19', 'mm10': 'M4' }
ANNO_ALLOWED = { 'hg19': [ ANNO_DEFAULTS['hg19'] ],
                 'mm10': [ ANNO_DEFAULTS['mm10'], 'M2', 'M3' ] }
ANNO_DEFAULT = ANNO_DEFAULTS[GENOME_DEFAULT]
''' Multiple annotations might be supported for each genome.'''

PROJECT_DEFAULT = 'scratchPad'
''' This the default DNA Nexus project to use for the long RNA-seq pipeline.'''

RESULT_FOLDER_DEFAULT = '/lrna/'
''' This the default location to place results folders for each experiment.'''

RUNS_LAUNCHED_FILE = "launchedRuns.txt"

REP_STEP_ORDER = {
    # for SE or PE the list in order of steps to run
    "se": [ "concatR1",             "align-tophat-se", "topBwSe", "align-star-se", "starBwSe", "quant-rsem" ],
    "pe": [ "concatR1", "concatR2", "align-tophat-pe", "topBwPe", "align-star-pe", "starBwPe", "quant-rsem" ]
    # examples for testing build_simple_steps
    #"se": [ "align-tophat-se", "align-star-se", "quant-rsem" ],
    #"pe": [ "align-tophat-pe", "align-star-pe", "quant-rsem" ]
    }
'''The (artifically) linear order of all pipeline steps for single or paired-end.'''

REP_STEPS = {
    # for each step: app, list of any params, inputs and results (both as fileToken: app_obj_name)
    # TODO: Any results files not listed here would not be 'deprecated' on reruns.
    "concatR1": {
                "app":     "concat-fastqs",
                "params":  { "concat_id":  "concat_id" },
                "inputs":  { "reads1_set": "reads_set" },
                "results": { "reads1":     "reads"     }
    },
    "concatR2": {
                "app":     "concat-fastqs",
                "params":  { "concat_id2": "concat_id" },
                "inputs":  { "reads2_set": "reads_set" },
                "results": { "reads2":     "reads"     }
    },
    "align-tophat-se": {
                "app":     "align-tophat-se",
                "params":  { "library_id":   "library_id" }, #, "nthreads"
                "inputs":  { "reads1":       "reads",
                             "tophat_index": "tophat_index" },
                "results": { "tophat_bam":   "tophat_bam" }
    },
    "align-tophat-pe": {
                "app":     "align-tophat-pe",
                "params":  { "library_id":   "library_id" }, #, "nthreads"
                "inputs":  { "reads1":       "reads_1",
                             "reads2":       "reads_2",
                             "tophat_index": "tophat_index" },
                "results": { "tophat_bam":   "tophat_bam" }
    },
    "topBwSe":  {
                "app":     "bam-to-bigwig-unstranded",
                "inputs":  { "tophat_bam":     "bam_file",
                             "chrom_sizes":    "chrom_sizes" },
                "results": { "tophat_all_bw":  "all_bw",
                             "tophat_uniq_bw": "uniq_bw" }
    },
    "topBwPe":  {
                "app":     "bam-to-bigwig-stranded",
                "inputs":  { "tophat_bam":           "bam_file",
                             "chrom_sizes":          "chrom_sizes" },
                "results": { "tophat_minus_all_bw":  "minus_all_bw",
                             "tophat_minus_uniq_bw": "minus_uniq_bw",
                             "tophat_plus_all_bw":   "plus_all_bw",
                             "tophat_plus_uniq_bw":  "plus_uniq_bw" }
    },
    "align-star-se":   {
                "app":     "align-star-se",
                "params":  { "library_id":      "library_id" }, #, "nthreads"
                "inputs":  { "reads1":          "reads",
                             "star_index":      "star_index" },
                "results": { "star_genome_bam": "star_genome_bam",
                             "star_anno_bam":   "star_anno_bam",
                             "star_log":        "star_log" }
    },
    "align-star-pe":   {
                "app":     "align-star-pe",
                "params":  { "library_id":      "library_id" }, #, "nthreads"
                "inputs":  { "reads1":          "reads_1",
                             "reads2":          "reads_2",
                             "star_index":      "star_index" },
                "results": { "star_genome_bam": "star_genome_bam",
                             "star_anno_bam":   "star_anno_bam",
                             "star_log":        "star_log" }
    },
    "starBwSe": {
                "app":     "bam-to-bigwig-unstranded",
                "inputs":  { "star_genome_bam": "bam_file",
                             "chrom_sizes":     "chrom_sizes" },
                "results": { "star_all_bw":     "all_bw",
                             "star_uniq_bw":    "uniq_bw" }
    },
    "starBwPe": {
                "app":     "bam-to-bigwig-stranded",
                "inputs":  { "star_genome_bam":    "bam_file",
                             "chrom_sizes":        "chrom_sizes" },
                "results": { "star_minus_all_bw":  "minus_all_bw",
                             "star_minus_uniq_bw": "minus_uniq_bw",
                             "star_plus_all_bw":   "plus_all_bw",
                             "star_plus_uniq_bw":  "plus_uniq_bw" }
    },
    "quant-rsem":     {
                "app":     "quant-rsem",
                "params":  { "paired_end":        "paired_end" },  #, "nthreads", "rnd_seed"
                "inputs":  { "star_anno_bam":     "star_anno_bam",
                             "rsem_index":        "rsem_index" },
                "results": { "rsem_iso_results":  "rsem_iso_results",
                             "rsem_gene_results": "rsem_gene_results" }
                }
    }

FILE_GLOBS = {
    # For looking up previous result files, use wild-cards
    "reads1":               "/*_reads_concat.fq.gz",
    "reads2":               "/*_reads2_concat.fq.gz",
    "tophat_bam":           "/*_tophat.bam",
    "tophat_minus_all_bw":  "/*_tophat_minusAll.bw",
    "tophat_minus_uniq_bw": "/*_tophat_minusUniq.bw",
    "tophat_plus_all_bw":   "/*_tophat_plusAll.bw",
    "tophat_plus_uniq_bw":  "/*_tophat_plusUniq.bw",
    "tophat_all_bw":        "/*_tophat_all.bw",
    "tophat_uniq_bw":       "/*_tophat_uniq.bw",
    "star_genome_bam":      "/*_star_genome.bam",
    "star_anno_bam":        "/*_star_anno.bam",
    "star_log":             "/*_Log.final.out",
    "star_minus_all_bw":    "/*_star_genome_minusAll.bw",
    "star_minus_uniq_bw":   "/*_star_genome_minusUniq.bw",
    "star_plus_all_bw":     "/*_star_genome_plusAll.bw",
    "star_plus_uniq_bw":    "/*_star_genome_plusUniq.bw",
    "star_all_bw":          "/*_star_genome_all.bw",
    "star_uniq_bw":         "/*_star_genome_uniq.bw",
    "rsem_iso_results":     "/*_rsem.isoforms.results",
    "rsem_gene_results":    "/*_rsem.genes.results"
    }

GENOME_REFERENCES = {
    # For looking up reference file names.
    # TODO: should remove annotation if only one per genome
    # TODO: should use ACCESSION based fileNames
    "tophat_index":  {
                    "hg19": {
                            "female":   {
                                        "v19": "hg19_female_v19_ERCC_tophatIndex.tgz"
                                        },
                            "male":     {
                                        "v19": "hg19_male_v19_ERCC_tophatIndex.tgz"
                                        }
                            },
                    "mm10": {
                            "female":   {
                                        "M2":  "mm10_female_M2_ERCC_tophatIndex.tgz",
                                        "M3":  "mm10_female_M3_ERCC_tophatIndex.tgz",
                                        "M4":  "mm10_female_M4_ERCC_tophatIndex.tgz"
                                        },
                            "male":     {
                                        "M2":  "mm10_male_M2_ERCC_tophatIndex.tgz",
                                        "M3":  "mm10_male_M3_ERCC_tophatIndex.tgz",
                                        "M4":  "mm10_male_M4_ERCC_tophatIndex.tgz"
                                        }
                            }
                    },
    "star_index":    {
                    "hg19": {
                            "female":   {
                                        "v19": "hg19_female_v19_ERCC_starIndex.tgz"
                                        },
                            "male":     {
                                        "v19": "hg19_male_v19_ERCC_starIndex.tgz"
                                        }
                            },
                    "mm10": {
                            "female":   {
                                        "M2":  "mm10_female_M2_ERCC_starIndex.tgz",
                                        "M3":  "mm10_female_M3_ERCC_starIndex.tgz",
                                        "M4":  "mm10_female_M4_ERCC_starIndex.tgz"
                                        },
                            "male":     {
                                        "M2":  "mm10_male_M2_ERCC_starIndex.tgz",
                                        "M3":  "mm10_male_M3_ERCC_starIndex.tgz",
                                        "M4":  "mm10_male_M4_ERCC_starIndex.tgz"
                                        }
                            }
                    },
    "rsem_index":    {
                    "hg19": {
                            "v19": "hg19_male_v19_ERCC_rsemIndex.tgz"
                            },
                    "mm10": {
                            "M2":  "mm10_male_M2_ERCC_rsemIndex.tgz",
                            "M3":  "mm10_male_M3_ERCC_rsemIndex.tgz",
                            "M4":  "mm10_male_M4_ERCC_rsemIndex.tgz"
                            }
                    },
    "chrom_sizes":   {
                    "hg19": {
                            "female":   "female.hg19.chrom.sizes",
                            "male":     "male.hg19.chrom.sizes"
                            },
                    "mm10": {
                            "female":   "female.mm10.chrom.sizes",
                            "male":     "male.mm10.chrom.sizes"
                            }
                    }
    }

APPLETS = {}
# Used for caching applets that might be called more than once in pipeline
FILES = {}
# Used for caching file dxlinks that might be needed more than once in building the workflow

def get_args():
    '''Parse the input arguments.'''
    ### PIPELINE SPECIFIC
    ap = argparse.ArgumentParser(description="Launches long RNA-seq pipeline analysis for " +
                "one replicate on single or paired-end reads. Can be run repeatedly and will " +
                "launch only the steps that are needed to finish the pipeline. All results " +
                "will be placed in the folder /<resultsLoc>/<experiment>/<replicate>.")
    ### PIPELINE SPECIFIC

    ap.add_argument('-e', '--experiment',
                    help='ENCODED experiment accession',
                    required=True)

    ap.add_argument('--br', '--biological-replicate',
                    help="Biological replicate number (default: 1)",
                    type=int,
                    default='1',
                    required=True)

    ap.add_argument('--tr', '--technical-replicate',
                    help="Technical replicate number (default: 1)",
                    type=int,
                    default='1',
                    required=False)

    ### PIPELINE SPECIFIC
    # TODO: should remove annotation if only one per genome
    ap.add_argument('-a', '--annotation',
                    help="Label of annotation (default: '" + ANNO_DEFAULT + "')",
                    choices=[ANNO_DEFAULT, 'M2','M3','M4'],
                    default=ANNO_DEFAULT,
                    required=False)
    ### PIPELINE SPECIFIC

    ap.add_argument('--project',
                    help="Project to run analysis in (default: '" + PROJECT_DEFAULT + "')",
                    default=PROJECT_DEFAULT,
                    required=False)

    ap.add_argument('--refLoc',
                    help="The location to find reference files (default: '" + \
                            dxencode.REF_PROJECT_DEFAULT + ":" + dxencode.REF_FOLDER_DEFAULT + "')",
                    default=dxencode.REF_FOLDER_DEFAULT,
                    required=False)

    ap.add_argument('--resultsLoc',
                    help="The location to to place results folders (default: '<project>:" + \
                                                                    RESULT_FOLDER_DEFAULT + "')",
                    default=RESULT_FOLDER_DEFAULT,
                    required=False)

    ap.add_argument('--run',
                    help='Run the workflow after assembling it.',
                    action='store_true',
                    required=False)

    ap.add_argument('--test',
                    help='Test run only, do not launch anything.',
                    action='store_true',
                    required=False)

    ap.add_argument('--force',
                    help='Force rerunning all steps.',
                    action='store_true',
                    required=False)

    #ap.add_argument('-x', '--export',
    #                help='Export generic Workflow (no inputs) to DNA Nexus project',
    #                action='store_true',
    #                required=False)

    return ap.parse_args()

def pipeline_specific_vars(args,verbose=False):
    '''Adds pipeline specific variables to a dict, for use building the workflow.'''
    # psv can contain any variables, but it must contain these at a minimum:
    # - Any non-file input param needed to launch the workflow
    # - 'resultFolder' - full dx path (without project) to the results folder of the specific run
    # - 'name' - A short name used for specific workflow run.
    # - 'description' - generic description of the pipeline.
    # - 'title'/['subtitle'] for command line output announcing what will be done
    # - Should also contain such things as:
    # - 'organism', 'gender', 'experiment', 'replicate' (if appropriate),
    # - 'pairedEnd' (boolean, if appropriate)

    # Start with dict containing common variables
    print "Retrieving experiment specifics..."
    psv = dxencode.common_variables(args,RESULT_FOLDER_DEFAULT,controls=False)
    if psv['exp_type'] != 'long-rna-seq':
        print "Experiment %s is not for long-rna-seq but for '%s'" \
                                                            % (psv['experiment'],psv['exp_type'])
        sys.exit(1)
    
    # Could be multiple annotations supported per genome
    psv['annotation'] = args.annotation
    if psv['genome'] != GENOME_DEFAULT and psv['annotation'] == ANNO_DEFAULT:
        psv['annotation'] = ANNO_DEFAULTS[psv['genome']]
    if psv['annotation'] not in ANNO_ALLOWED[psv['genome']]:
        print psv['genome']+" has no "+psv['annotation']+" annotation."
        sys.exit(1)
    
    # Some specific settings
    psv['nthreads']   = 8
    psv['rnd_seed']   = 12345

    # run will either be for combined or single rep.
    if not psv['combined']:
        run = psv['reps']['a']  # If not combined then run will be for the first (only) replicate
    else:
        run = psv
        print "Long-RNA-seq pipeline currently does not support combined-replicate processing."
        print mapping
        sys.exit(1)

    # workflow labeling
    psv['description'] = "The ENCODE RNA Seq pipeline for long RNAs"
    run['name'] = "lrna_"+psv['genome']
    if psv['genome'] == 'mm10':
        run['name'] += psv['annotation']
    if psv['gender'] == 'female':
        run['name'] += "XX"
    else:
        run['name'] += "XY"
    if psv['paired_end']:
        run['title'] = "long RNA-seq paired-end "
        run['name'] += "PE"
    else:
        run['title'] = "long RNA-seq single-end "
        run['name'] += "SE"
    run['title']   += psv['experiment']+" - "+run['rep_tech'] + " (library '"+run['library_id']+"')"
    run['subTitle'] = psv['genome']+", "+psv['gender']+" and annotation '"+psv['annotation']+"'."
    run['name']    += "_"+psv['experiment']+"_"+run['rep_tech']

    if verbose:
        print "Pipeline Specific Vars:"
        print json.dumps(psv,indent=4)
    return psv


def find_ref_files(priors,psv):
    '''Locates all reference files based upon gender, organism and annotation.'''
    refFiles = {}
    topIx = psv['refLoc']+GENOME_REFERENCES['tophat_index'][psv['genome']][psv['gender']][psv['annotation']]
    topIxFid = dxencode.find_file(topIx,dxencode.REF_PROJECT_DEFAULT)
    if topIxFid == None:
        sys.exit("ERROR: Unable to locate TopHat index file '" + topIx + "'")
    else:
        priors['tophat_index'] = topIxFid

    starIx = psv['refLoc']+GENOME_REFERENCES['star_index'][psv['genome']][psv['gender']][psv['annotation']]
    starIxFid = dxencode.find_file(starIx,dxencode.REF_PROJECT_DEFAULT)
    if starIxFid == None:
        sys.exit("ERROR: Unable to locate STAR index file '" + starIx + "'")
    else:
        priors['star_index'] = starIxFid

    rsemIx = psv['refLoc']+GENOME_REFERENCES['rsem_index'][psv['genome']][psv['annotation']]
    rsemIxFid = dxencode.find_file(rsemIx,dxencode.REF_PROJECT_DEFAULT)
    if rsemIxFid == None:
        sys.exit("ERROR: Unable to locate RSEM index file '" + rsemIx + "'")
    else:
        priors['rsem_index'] = rsemIxFid

    chromSizes = psv['refLoc']+GENOME_REFERENCES['chrom_sizes'][psv['genome']][psv['gender']]
    chromSizesFid = dxencode.find_file(chromSizes,dxencode.REF_PROJECT_DEFAULT)
    if chromSizesFid == None:
        sys.exit("ERROR: Unable to locate Chrom Sizes file '" + chromSizes + "'")
    else:
        priors['chrom_sizes'] = chromSizesFid
    psv['ref_files'] = GENOME_REFERENCES.keys()


#######################
def main():

    args = get_args()
    print "Retrieving pipeline specifics..."
    psv = pipeline_specific_vars(args)

    project = dxencode.get_project(psv['project'])
    projectId = project.get_id()

    #print "Building apps dictionary..."
    pipeRepPath = REP_STEP_ORDER['se']
    if psv['paired_end']:
        pipeRepPath = REP_STEP_ORDER['pe']
    #pipeRepSteps, file_globs = dxencode.build_simple_steps(pipeRepPath,projectId,verbose=True)
    pipeRepSteps = REP_STEPS
    file_globs = FILE_GLOBS
    for rep in psv['reps'].values():
        rep['path'] = pipeRepPath

    # finding fastqs and prior results in a stadardized way
    dxencode.finding_rep_inputs_and_priors(psv,pipeRepSteps,file_globs,project,args.test)

    # finding pipeline specific reference files in a stadardized way
    dxencode.find_all_ref_files(psv,find_ref_files)

    # deterine steps to run in a stadardized way
    dxencode.determine_steps_needed(psv, pipeRepSteps, None, projectId, args.force)

    # Preperation is done. At this point on we either run rep 'a' or combined.
    run = psv['reps']['a']
    run['steps'] = pipeRepSteps
        
    dxencode.report_build_launch(psv, run, projectId, test=args.test, launch=args.run)

    print "(success)"

if __name__ == '__main__':
    main()

