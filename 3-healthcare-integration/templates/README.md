# templates/

`imaging_study_summary.opt` — the openEHR operational template (ADL 1.4 OPT XML) the bridge uploads to
EHRbase at startup. It is not committed: build it in the openEHR Archetype Designer from

- `openEHR-EHR-COMPOSITION.report.v1`
- `openEHR-EHR-OBSERVATION.imaging_exam_result.v0` (CKM) with a `CLUSTER.multimedia_source.v1` slot

and export as OPT with template id `imaging_study_summary`. The FLAT paths written by
`pipeline.imaging_summary_flat()` assume the element names used in that template; if you rename nodes in
the Designer, update the dict there. EHRbase rejects a composition whose paths do not exist in the OPT, so a
mismatch fails loudly at the first study rather than silently storing a half-empty record.
