# Inter-reader agreement and adjudication plan

## Readers
>= 2 independent readers per case in both pathways (3 preferred for Fleiss kappa); 1 adjudicator (experienced neuroradiologist or
neurologist with SWI expertise) who is not one of the readers. Reader log per reader: training, years, prior exposure to these patients
or to the AI meter.

## Statistics (`reference_audit/agreement.py`; every kappa / overlap with a 95 % patient-cluster bootstrap CI, 2,000 resamples, seed 20261119 - items of one patient are resampled together)
| Question | Unit | Statistic |
|---|---|---|
| Category agreement, pathway B | object | Cohen kappa per reader pair (4 classes and cSS-yes = definite+probable vs not); Fleiss kappa when every reader rated every object; % agreement |
| Lesion presence | patient side (L / R) | Cohen / Fleiss kappa on cSS present yes / no / indeterminate |
| Multifocality | patient side | unweighted and quadratic-weighted kappa on 0 / 1 / 2 |
| Lesion localisation | lesion | marks of different readers within 5 mm = same lesion (single-linkage clusters); detection overlap 2M / (n1 + n2); counts found by one reader only |
| Confidence | object / lesion | quadratic-weighted kappa on 1-5 |
| Intra-reader | 10 % re-read after >= 4 weeks | same statistics, session 1 vs 2 |
Kappa is reported with prevalence (kappa is unstable when one class dominates) and with raw agreement; Gwet AC1 can be added if
prevalence is extreme.

## Disagreement report and adjudication
1. `agreement.py` writes `disagreements.csv` (every object / lesion cluster where categories differ, incl. "marked by one reader only")
   and `adjudication_TEMPLATE.csv`.
2. The adjudicator reviews the images with the readers' categories and comments (anonymised), fills `adjudicated_category`
   (+ non-cSS type, note) and saves `adjudication.csv`. "indeterminate" remains allowed.
3. The independent reads are never edited; the reference label = unanimous category, else adjudicated category, else "unresolved"
   (reported, excluded from the primary analysis, included in a sensitivity analysis both ways).
4. Analyses are reported for: (a) adjudicated reference, (b) each reader alone, (c) definite-only and definite+probable.

## Sample-size guidance
14 patients x 2 readers give kappa CIs of roughly +-0.2 at kappa ~0.6 - enough to show whether agreement is fair or substantial, not to
compare readers. Expanding to the LEMON negatives and new CAA cases improves specificity estimates more than adding readers.
