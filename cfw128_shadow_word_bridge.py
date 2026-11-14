"""Explicit synthetic shadow only; no production caller or state writes.

Reads caller-owned canonical App snapshots, explicit synthetic boundaries and
current Word context. Consumes existing numeric/placement, signature, template
and postprocessor authorities. Owns only ephemeral consistency and figure
lifetime; no persistence, UI, engineering, renderer or report-text authority.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from io import BytesIO
import matplotlib.pyplot as plt
from docxtpl import DocxTemplate
from project_state import fingerprint, prepare_calculations
from pumping_simulation import source_signature
from well_report import canonical_report_source, prepared_well_report, postprocess_well_report
from cement_chart_report import prepared_cement_report
from well_schematic_adapter import source_signature as schematic_source_signature, prepare_schematic
from phase_10_procedure import TEMPLATE_PATH, document_signature, _word_quantity_context
from cfw128_er03_numeric_adapter import NumericBoundary, NumericEvidence, _primitive, run_numeric_test_case, validate_numeric_evidence, render_numeric_test_charts
from cfw128_c2e7_native_placement import NativePlacementAssessment, assess_native_placement
from cfw128_c2e8_post_pull_review import PostPullConditions, PostPullReview, assess_post_pull, validate_post_pull_review

SCHEMA='CFW128_DISABLED_WORD_SHADOW_V1'
POST_PULL_SIDECAR_SCHEMA='CFW128_DISABLED_SHADOW_POST_PULL_V1'


@dataclass(frozen=True,slots=True)
class ShadowPostPullEvidence:
    """Explicit synthetic sidecar; never part of the Word/chart payload."""
    shadow_identity: str
    source_identity: str
    review: PostPullReview
    projection_identity: str
    schema: str=field(default=POST_PULL_SIDECAR_SCHEMA,init=False)
    status: str=field(default='DISABLED_SHADOW_POST_PULL_HOLD',init=False)
    evidence_class: str=field(default='SYNTHETIC_TEST_ONLY',init=False)
    currentness: str=field(default='NOT_CURRENTNESS_PROOF',init=False)
    qualification: str=field(default='NOT_GRANTED',init=False)
    final_field_toc: str=field(default='FINAL_FIELD_TOC_NOT_EVALUATED',init=False)
    enabled: bool=field(default=False,init=False)
    ready_to_run: bool=field(default=False,init=False)
    hb_admissible: bool=field(default=False,init=False)
    hydraulic_admissible: bool=field(default=False,init=False)
    chart_admissible: bool=field(default=False,init=False)
    scientifically_qualified: bool=field(default=False,init=False)

    def __post_init__(self):
        _primitive(self)
        if type(self.review) is not PostPullReview:raise TypeError('Typed native post-pull review required.')
        self.review.__post_init__()
        if (self.schema!=POST_PULL_SIDECAR_SCHEMA or self.status!='DISABLED_SHADOW_POST_PULL_HOLD'
                or self.evidence_class!='SYNTHETIC_TEST_ONLY' or self.currentness!='NOT_CURRENTNESS_PROOF'
                or self.qualification!='NOT_GRANTED' or self.final_field_toc!='FINAL_FIELD_TOC_NOT_EVALUATED'):
            raise ValueError('Disabled synthetic sidecar declarations required.')
        wanted=fingerprint([POST_PULL_SIDECAR_SCHEMA,self.shadow_identity,self.source_identity,_primitive(self.review)])
        if wanted!=self.projection_identity:raise ValueError('Shadow post-pull projection differs.')


def prepare_shadow_post_pull(state,evidence,*,expected_app_source_sha,boundary,conditions):
    """Opt-in read-only sidecar of the same validated numeric result; no solver.

    Consumes existing source/parent and Batch A validation authorities. No state,
    geometry, physics, persistence, Word, chart or production-route authority.
    Conditions are explicit model declarations, not acquired field observations.
    """
    if type(conditions) is not PostPullConditions:raise TypeError('Explicit typed post-pull conditions required.')
    conditions.__post_init__()
    _validate(state,evidence,expected_app_source_sha,boundary)
    review=assess_post_pull(state,evidence.numeric,expected_app_source_sha=expected_app_source_sha,conditions=conditions)
    identity=fingerprint([POST_PULL_SIDECAR_SCHEMA,evidence.projection_identity,evidence.source_identity,_primitive(review)])
    sidecar=ShadowPostPullEvidence(evidence.projection_identity,evidence.source_identity,review,identity)
    validate_shadow_post_pull(state,evidence,sidecar,expected_app_source_sha=expected_app_source_sha,boundary=boundary,conditions=conditions)
    return sidecar


def validate_shadow_post_pull(state,evidence,sidecar,*,expected_app_source_sha,boundary,conditions):
    """Fresh supplied-source consistency; unkeyed IDs are not currentness proof."""
    if type(conditions) is not PostPullConditions:raise TypeError('Explicit typed post-pull conditions required.')
    conditions.__post_init__()
    _validate(state,evidence,expected_app_source_sha,boundary)
    if type(sidecar) is not ShadowPostPullEvidence:raise TypeError('Typed shadow post-pull evidence required.')
    sidecar.__post_init__()
    if (sidecar.shadow_identity!=evidence.projection_identity or sidecar.source_identity!=evidence.source_identity
            or sidecar.review.numeric_identity!=evidence.numeric.projection_identity
            or sidecar.review.placement_identity!=evidence.placement.projection_identity):
        raise ValueError('Mixed shadow parent or native post-pull evidence.')
    validate_post_pull_review(state,evidence.numeric,sidecar.review,expected_app_source_sha=expected_app_source_sha,conditions=conditions)
    _validate(state,evidence,expected_app_source_sha,boundary)


def _source(state,sha,boundary,engine):
    if type(state) is not dict or type(boundary) is not NumericBoundary:
        raise TypeError('Explicit App snapshot and synthetic NumericBoundary required.')
    return fingerprint([SCHEMA,sha,state,_primitive(boundary),engine])


@dataclass(frozen=True,slots=True)
class ShadowEvidence:
    app_source_sha: str
    source_identity: str
    boundary: NumericBoundary
    engine: str
    numeric: NumericEvidence
    placement: NativePlacementAssessment
    context_identity: str | None
    document_identity: str | None
    projection_identity: str
    schema: str=field(default=SCHEMA,init=False)
    evidence_class: str=field(default='SYNTHETIC_TEST_ONLY',init=False)
    currentness: str=field(default='NOT_CURRENTNESS_PROOF',init=False)
    qualification: str=field(default='NOT_GRANTED',init=False)
    final_post_pull_toc: str=field(default='FINAL_POST_PULL_TOC_NOT_EVALUATED',init=False)
    enabled: bool=field(default=False,init=False)
    ready_to_run: bool=field(default=False,init=False)
    hb_admissible: bool=field(default=False,init=False)
    hydraulic_admissible: bool=field(default=False,init=False)
    chart_admissible: bool=field(default=False,init=False)
    scientifically_qualified: bool=field(default=False,init=False)

    def __post_init__(self):
        _primitive(self)
        if (self.schema!=SCHEMA or self.evidence_class!='SYNTHETIC_TEST_ONLY'
                or self.currentness!='NOT_CURRENTNESS_PROOF' or self.qualification!='NOT_GRANTED'
                or self.final_post_pull_toc!='FINAL_POST_PULL_TOC_NOT_EVALUATED'):
            raise ValueError('Disabled synthetic shadow declarations required.')
        wanted=fingerprint([SCHEMA,self.app_source_sha,self.source_identity,_primitive(self.boundary),self.engine,
                            _primitive(self.numeric),_primitive(self.placement),self.context_identity,self.document_identity])
        if wanted!=self.projection_identity:raise ValueError('Shadow projection differs.')


def _context(state,context):
    checked=deepcopy(state)
    issues=prepare_calculations(checked)
    if issues:raise ValueError('SHADOW WORD HOLD: '+' | '.join(issues))
    if (type(context) is not dict or context.get('pumping_simulation_source')!=source_signature(checked)
            or context.get('well_profile_source')!=fingerprint(canonical_report_source(checked))
            or context.get('well_schematic_source')!=schematic_source_signature(checked)
            or fingerprint(context.get('well_profile_report'))!=fingerprint(prepared_well_report(checked))
            or fingerprint(context.get('cement_chart_report'))!=fingerprint(prepared_cement_report(checked))):
        raise ValueError('Word context does not match fresh supplied App source.')
    return fingerprint(context),document_signature(context,TEMPLATE_PATH)


def prepare_shadow(state, *, expected_app_source_sha, boundary, engine='vertical', word_context=None):
    """Explicit native execution only. Incomplete inputs fail closed, no fallback."""
    identity=_source(state,expected_app_source_sha,boundary,engine)
    captured=deepcopy(state)
    numeric=run_numeric_test_case(captured,expected_app_source_sha=expected_app_source_sha,
        boundary=boundary,engine=engine,stepping='event_aligned_test_only')
    if numeric.native_observation is None:
        raise ValueError('SHADOW HOLD: native evidence absent; '+','.join(numeric.holds))
    placement=assess_native_placement(captured,numeric,expected_app_source_sha=expected_app_source_sha)
    if identity!=_source(state,expected_app_source_sha,boundary,engine):raise ValueError('Source changed during preparation.')
    context_identity,document_identity=(None,None) if word_context is None else _context(state,word_context)
    projection=fingerprint([SCHEMA,expected_app_source_sha,identity,_primitive(boundary),engine,_primitive(numeric),_primitive(placement),context_identity,document_identity])
    return ShadowEvidence(expected_app_source_sha,identity,boundary,engine,numeric,placement,context_identity,document_identity,projection)


def _validate(state,evidence,sha,boundary):
    if type(evidence) is not ShadowEvidence:raise TypeError('Typed shadow evidence required.')
    evidence.__post_init__()
    if (evidence.engine not in ('vertical','directional')
            or evidence.numeric.engine!='event_aligned_'+evidence.engine
            or evidence.numeric.native_observation is None):
        raise ValueError('Shadow requires matching event-aligned native evidence.')
    if (_source(state,sha,boundary,evidence.engine)!=evidence.source_identity
            or evidence.app_source_sha!=sha or _primitive(boundary)!=_primitive(evidence.boundary)):
        raise ValueError('Stale or mixed shadow source/boundary.')
    validate_numeric_evidence(evidence.numeric)
    current=assess_native_placement(state,evidence.numeric,expected_app_source_sha=sha)
    if _primitive(current)!=_primitive(evidence.placement):raise ValueError('Stale or mixed native placement.')


@contextmanager
def shadow_pumping_report(state,evidence,*,expected_app_source_sha,boundary):
    """Fresh visual-only render; caller must consume inside this lifetime."""
    _validate(state,evidence,expected_app_source_sha,boundary)
    figure=render_numeric_test_charts(evidence.numeric)
    try:
        _validate(state,evidence,expected_app_source_sha,boundary)
        yield {'applicable':True,'figure':figure,'result':evidence,'schema':SCHEMA,
               'warnings':('SYNTHETIC_TEST_ONLY / DISABLED / HOLD',
                           'Raw Qout = ANNULAR_MOUTH_PLUS_PIPE_HEAD; not field Flowline returns',
                           *evidence.placement.holds)}
    finally:
        plt.close(figure)


def shadow_word_bytes(state,evidence,context,*,expected_app_source_sha,boundary):
    """Render trusted canonical context to caller-owned shadow bytes only.

    Context/source hashes prove consistency, not authenticity or external live
    currentness. No shadow diagnostic/TOC text is added to the Word template.
    """
    _validate(state,evidence,expected_app_source_sha,boundary)
    if _context(state,context)!=(evidence.context_identity,evidence.document_identity):
        raise ValueError('Stale, mixed or unbound Word context.')
    captured=deepcopy(context);context_identity=fingerprint(captured)
    document_identity=document_signature(captured,TEMPLATE_PATH)
    with shadow_pumping_report(state,evidence,expected_app_source_sha=expected_app_source_sha,boundary=boundary) as pumping:
        template=DocxTemplate(TEMPLATE_PATH);template.render(_word_quantity_context(captured))
        raw=BytesIO();template.save(raw)
        result=postprocess_well_report(raw.getvalue(),captured['well_profile_report'],captured['note_vertical'],
            captured['cement_chart_report'],captured['centralizer_report'],pumping_report=pumping,
            schematic_report=prepare_schematic(state),section_vi_programs={k:captured[k] for k in ('has_preflush','has_spacer')})
        _validate(state,evidence,expected_app_source_sha,boundary)
        if context_identity!=fingerprint(context) or document_identity!=document_signature(context,TEMPLATE_PATH):
            raise ValueError('Word context/template changed during shadow rendering.')
    return {'bytes':result,'schema':SCHEMA,'source_identity':evidence.source_identity,
            'result':evidence,'status':'DISABLED_SHADOW_WORD_HOLD',
            'numeric_identity':evidence.numeric.projection_identity,'placement_identity':evidence.placement.projection_identity,
            'context_identity':context_identity,'document_identity':document_identity,
            'currentness':'NOT_CURRENTNESS_PROOF','qualification':'NOT_GRANTED','warnings':pumping['warnings']}
