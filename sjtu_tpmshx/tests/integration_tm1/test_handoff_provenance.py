"""Preparation and execution origins survive independent file handoff."""
import pytest
from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.preprocess import api as preparation
from sjtu_tpmshx.solvers import api as execution
from sjtu_tpmshx.domain.provenance import repository_revision, source_context
from sjtu_tpmshx.tests.test_evaluator_frozen_values import _FAST_CFG, _X_NONUNIF


@pytest.mark.slow
def test_provenance_survives_case_and_result(tmp_path, monkeypatch):
    prepared = {'code':{'revision':'preparation-revision'}, 'data':{'declared_revision':'input-revision'}}
    solved = {'code':{'revision':'solver-revision'}, 'data':{'declared_revision':'solver-data-revision'}}
    monkeypatch.setattr(preparation, 'source_context', lambda: prepared)
    monkeypatch.setattr(execution, 'source_context', lambda: solved)
    case = preparation.prepare_screening_2d(_X_NONUNIF.copy(),dict(_FAST_CFG),case_id='provenance')
    save_case(case,tmp_path/'case.yaml')
    result = execution.run_case(load_case(tmp_path/'case.yaml'))
    save_result(result,tmp_path/'result.h5')
    result = load_result(tmp_path/'result.h5')
    assert result.metadata['provenance']['preparation']==prepared
    assert result.metadata['provenance']['execution']==solved


def test_missing_repository_is_explicit(tmp_path):
    assert repository_revision(tmp_path)==dict(revision=None,tracked_changes=None,status='unavailable')
    context = source_context()
    assert context['code']['package_version']
    assert 'declared_revision' in context['data']
    assert 'repository' in context['data']
