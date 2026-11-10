#!/bin/zsh
# Bring T1 (and FLAIR) anatomy onto the SWI grid (v4).
# usage: prep_anat.sh SUBJECT_ID --t1 T1.nii(.gz) [--flair FLAIR.nii(.gz)] [--recon]
#   --recon  full FreeSurfer recon-all on the T1 (about 1-3 h on an M3): gives Destrieux sulcal
#            labels -> true SULCAL multifocality scoring. Re-used if subjects/ID already finished.
#   default  SynthSeg --parc --robust on the T1 (minutes): sharper cortex/CSF than SynthSeg on SWI,
#            but no sulcal labels (scoring stays Euclidean).
# Needs data/ID_swi.nii (run_css.sh imports it). Writes, all on the SWI grid, in work/:
#   ID_t1seg_swispace.nii.gz    aseg + DK cortex labels  -> align_seg.py / detect_css.py
#   ID_a2009s_swispace.nii.gz   Destrieux labels         -> score_css.py (recon-all only)
#   ID_flair_swispace.nii.gz    FLAIR                    -> detect_css.py (acute cSAH check)
#   ID_swi2t1.lta, ID_flair2swi.lta   registrations: ALWAYS check them with the printed freeview line
# Use the 3-D T1 (MPRAGE / SPGR / BRAVO) and the 3-D or 2-D FLAIR. Do NOT use the minIP series.
set -e
S=$1; shift 2>/dev/null || true
T1=""; FL=""; RECON=0
while [ $# -gt 0 ]; do
  case "$1" in
    --t1) T1=$2; shift 2;;
    --flair) FL=$2; shift 2;;
    --recon) RECON=1; shift;;
    *) echo "prep_anat.sh: unknown option $1"; exit 1;;
  esac
done
if [ -z "$S" ] || [ -z "$T1" ]; then
  echo "usage: prep_anat.sh SUBJECT_ID --t1 T1.nii [--flair FLAIR.nii] [--recon]"; exit 1
fi
# v4.17.2: stop at the first failed step (a typo in --t1 used to fall through and leave the old labels in place)
die() { echo "ERROR: $1 - nothing after this step was run; the previous labels are unchanged"; exit 1; }
[ -f "$T1" ] || die "T1 file not found: $T1"
B=${CSS_BASE:-$HOME/css_project}; W=$B/work
# always the project folder (FreeSurfer's setup script points SUBJECTS_DIR at its own install dir);
# set CSS_SUBJECTS_DIR to use a different folder
export SUBJECTS_DIR=${CSS_SUBJECTS_DIR:-$B/subjects}
SWI=$B/data/${S}_swi.nii
[ -f $SWI ] || { echo "ERROR: $SWI not found - run run_css.sh $S <swi> first"; exit 1; }
mkdir -p $W $SUBJECTS_DIR

echo "[a] T1: import"
# via a temporary file, so --t1 data/ID_t1.nii.gz (the copy imported earlier) also works
mri_convert "$T1" $B/data/${S}_t1_tmp.nii.gz > /dev/null || die "mri_convert could not read $T1"
mv $B/data/${S}_t1_tmp.nii.gz $B/data/${S}_t1.nii.gz

A2=""
if [ $RECON -eq 1 ] || [ -f $SUBJECTS_DIR/$S/mri/aparc.a2009s+aseg.mgz ]; then
  if [ ! -f $SUBJECTS_DIR/$S/mri/aparc.a2009s+aseg.mgz ]; then
    # v4.18: an unfinished subject folder (earlier failed run) blocks recon-all -i; keep it, renamed
    if [ -d $SUBJECTS_DIR/$S ]; then
      mv $SUBJECTS_DIR/$S $SUBJECTS_DIR/${S}_failed_$(date +%Y%m%d_%H%M%S)
      echo "    moved the unfinished $SUBJECTS_DIR/$S aside (${S}_failed_<date>)"
    fi
    echo "[b] recon-all -all (1-3 h; log: $W/${S}_recon.log)"
    # v5.2.6: FreeSurfer 8 adds -synthstrip -synthseg -synthmorph -fix-vsinus -fix-mca-dura ... by default
    # (etc/global-expert-options.v8.txt); its SynthStrip step reached 85 GB on M02 and froze a 36 GB Mac. -no-v8 = the
    # classic recon-all (watershed skull-strip, atlas aseg; a few GB). CSS_RECON_V8=1 keeps FreeSurfer's v8 defaults.
    V8OPT="-no-v8"; [ "${CSS_RECON_V8:-0}" = 1 ] && V8OPT=""
    echo "    recon-all options: -all -threads ${CSS_THREADS:-4} ${V8OPT:-(FreeSurfer v8 defaults)}"
    recon-all -s $S -i $B/data/${S}_t1.nii.gz -all $V8OPT -threads ${CSS_THREADS:-4} > $W/${S}_recon.log 2>&1 \
      || die "recon-all failed (see $W/${S}_recon.log)"
  else
    echo "[b] recon-all already finished for $S - re-using it"
  fi
  LAB=$SUBJECTS_DIR/$S/mri/aparc+aseg.mgz
  A2=$SUBJECTS_DIR/$S/mri/aparc.a2009s+aseg.mgz
  echo "[c] register SWI -> T1 (bbregister, boundary-based, T2*-like contrast)"
  bbregister --s $S --mov $SWI --reg $W/${S}_swi2t1.lta --t2 --init-coreg > $W/${S}_bbreg.log 2>&1 \
    || die "bbregister failed (see $W/${S}_bbreg.log)"
  # FreeSurfer 8 bbregister names its side files after an internal .dat (ID_swi2t1.dat.mincost), older ones .lta.mincost
  MC=$(ls $W/${S}_swi2t1.lta.mincost $W/${S}_swi2t1.dat.mincost 2>/dev/null | head -1)
  REGM=bbregister; COST=$( [ -n "$MC" ] && awk 'NR==1{print $1}' $MC 2>/dev/null || true)
  [ -n "$COST" ] && echo "    bbregister min cost $COST (FreeSurfer: < ~0.6 is typical for a good fit)"
else
  echo "[b] SynthSeg --parc --robust on the T1"
  mri_synthseg --i $B/data/${S}_t1.nii.gz --o $W/${S}_t1synthseg.nii.gz --parc --robust --threads ${CSS_THREADS:-8} > /dev/null || die "mri_synthseg failed"
  LAB=$W/${S}_t1synthseg.nii.gz
  # v5.2.4: the skull-stripped T1 is needed only here (recon-all strips the skull itself). SynthStrip peaked at 31 GB
  # on a 1 mm whole-head T1 (M01, 36 GB Mac): run it only when it is used, with a thread cap, messages kept
  # v5.2.5: run_css.sh with a T1 passes the SWI whole-head (CSS_SWI_HEAD=1): register whole head to whole head
  if [ "${CSS_SWI_HEAD:-0}" = 1 ]; then
    T1REF=$B/data/${S}_t1.nii.gz
  else
    echo "    T1 skull-strip (SynthStrip, ${CSS_THREADS:-4} threads)"
    mri_synthstrip -i $B/data/${S}_t1.nii.gz -o $W/${S}_t1_brain.nii.gz -t ${CSS_THREADS:-4} > $W/${S}_t1_synthstrip.log 2>&1 \
      || { tail -5 $W/${S}_t1_synthstrip.log; die "mri_synthstrip failed on the T1 (messages above; full log $W/${S}_t1_synthstrip.log)"; }
    T1REF=$W/${S}_t1_brain.nii.gz
  fi
  echo "[c] register SWI -> T1 (mri_coreg, rigid, mutual information)"
  mri_coreg --mov $SWI --ref $T1REF --reg $W/${S}_swi2t1.lta --dof 6 > $W/${S}_coreg.log 2>&1 \
    || die "mri_coreg failed (see $W/${S}_coreg.log)"
  REGM=mri_coreg; COST=""
fi

# v4.14 QC: registration method + cost (bbregister mincost; mri_coreg reports none) -> review/ID_qc.json
echo "$COST" | grep -Eq '^[0-9.eE+-]+$' || COST=null
printf '{"method": "%s", "cost": %s}\n' "$REGM" "$COST" > $W/${S}_reg.json
echo "[d] labels -> SWI grid (nearest neighbour)"
mri_vol2vol --mov $SWI --targ $LAB --lta $W/${S}_swi2t1.lta --inv --interp nearest \
  --o $W/${S}_t1seg_swispace.nii.gz > /dev/null || die "mri_vol2vol (labels -> SWI) failed"
if [ -n "$A2" ]; then
  mri_vol2vol --mov $SWI --targ $A2 --lta $W/${S}_swi2t1.lta --inv --interp nearest \
    --o $W/${S}_a2009s_swispace.nii.gz > /dev/null
fi

if [ -n "$FL" ]; then
  echo "[e] FLAIR: import, skull-strip, register -> SWI, resample"
  mri_convert "$FL" $B/data/${S}_flair.nii.gz > /dev/null
  if [ "${CSS_SWI_HEAD:-0}" = 1 ]; then   # v5.2.5: whole-head FLAIR to whole-head SWI; masked by swi_mask_from_t1.py
    FLB=$B/data/${S}_flair.nii.gz
  else
    mri_synthstrip -i $B/data/${S}_flair.nii.gz -o $W/${S}_flair_brain.nii.gz -t ${CSS_THREADS:-4} > $W/${S}_flair_synthstrip.log 2>&1 \
      || { tail -5 $W/${S}_flair_synthstrip.log; die "mri_synthstrip failed on the FLAIR (full log $W/${S}_flair_synthstrip.log)"; }
    FLB=$W/${S}_flair_brain.nii.gz
  fi
  mri_coreg --mov $FLB --ref $SWI --reg $W/${S}_flair2swi.lta --dof 6 > $W/${S}_flaircoreg.log 2>&1
  mri_vol2vol --mov $FLB --targ $SWI --lta $W/${S}_flair2swi.lta \
    --o $W/${S}_flair_swispace.nii.gz > /dev/null
fi

echo ""
echo "QC - labels must hug the SWI cortex in the CORONAL and SAGITTAL views too (an up-down slip is"
echo "invisible in axial slices); FLAIR must line up (toggle layers). detect_css.py reports label_shift_mm:"
echo "  freeview -v $SWI $W/${S}_t1seg_swispace.nii.gz:colormap=lut:opacity=0.3" \
     "$( [ -n "$FL" ] && echo "$W/${S}_flair_swispace.nii.gz:visible=0" )" \
     "$( [ -n "$A2" ] && echo "$W/${S}_a2009s_swispace.nii.gz:colormap=lut:opacity=0.3:visible=0" )"
echo "If misaligned: delete work/${S}_t1seg_swispace.nii.gz and the pipeline falls back to SWI SynthSeg."
