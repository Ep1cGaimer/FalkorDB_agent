"""Reference validity cannot bypass a separate exact-span support decision."""
import copy
import hashlib
import importlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def case(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'evals'))
    support = importlib.import_module('confirmatory.claim_support')
    meter = importlib.import_module('confirmatory.gemini_meter')
    text = 'class Actual:\n    pass\n\n# unrelated nearby comment\n'
    sha, oid, tree = 'a'*40, 'b'*40, 'c'*40
    raw = SimpleNamespace(repository='development', ref_records={},
        commits={sha:{'tree':tree}}, trees={tree:{'a.py':{'oid':oid,'coverage':'included'}}},
        blobs={oid:{'encoding':'utf-8','content':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}})
    citation = {'repository':raw.repository,'commit':sha,'path':'a.py','start_line':4,'end_line':4,
                'content_hash':raw.blobs[oid]['sha256']}
    answer = {'answer':'Actual is declared here.','citations':[citation],'gaps':[],'runtime_disposition':None}
    trace = [{'tool':'read_file','response':{'status':'OK','result':{'citation':citation,'content':'# unrelated nearby comment\n'}}}]
    class Model:
        started = time.monotonic()
        clock = staticmethod(time.monotonic)
        limits = SimpleNamespace(seconds=60)
        def __init__(self, decision):
            self.journal = meter.Journal(tmp_path/'review')
            self.decision, self.requests = decision, []
        def ask(self, system, contents, **kwargs):
            self.requests.append((system,copy.deepcopy(contents),kwargs))
            return json.dumps(self.decision)
        def summary(self):return {'synthetic':True,'provider_calls':0}
    return support, raw, answer, trace, Model


def decision(verdict='unsupported', indices=None):
    return {'all_material_claims_covered':True,'claims':[{'claim':'Actual is declared here.',
        'verdict':verdict,'citation_indices':[0] if indices is None else indices,
        'reason':'The exact cited span is a nearby comment, not the declaration.'}]}


def test_existing_reference_with_unrelated_lines_is_rejected_and_nearby_source_is_hidden(case):
    support, raw, answer, trace, Model = case
    model=Model(decision())
    result=support.review_source_claims(answer,trace,raw,model)
    assert result['reference_integrity']['valid'] is True
    assert result['material_claim_grounding']=='MODEL_REVIEW_REJECTED'
    payload=json.loads(model.requests[0][1][0]['parts'][0]['text'])
    assert payload['citations'][0]['exact_cited_lines']==[{'line':4,'text':'# unrelated nearby comment\n'}]
    assert 'class Actual:' not in json.dumps(payload)


@pytest.mark.parametrize('value',[decision('supported',[1]),decision('supported',[]),
    {'all_material_claims_covered':True,'claims':[]}])
def test_malformed_or_unanchored_support_review_cannot_pass(case,value):
    support,raw,answer,trace,Model=case
    result=support.review_source_claims(answer,trace,raw,Model(value))
    assert result['status']=='ERROR' and result['material_claim_grounding']=='UNVALIDATED'


def test_supported_claims_do_not_pass_when_reviewer_did_not_cover_all_material_claims(case):
    support,raw,answer,trace,Model=case
    value=decision('supported');value['all_material_claims_covered']=False
    result=support.review_source_claims(answer,trace,raw,Model(value))
    assert result['material_claim_grounding']=='MODEL_REVIEW_REJECTED'
