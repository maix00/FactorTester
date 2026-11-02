import numpy as np
import pytest

from tests.benchmarks.verify_paper_batch_stream import compare_formal_values, comparison_passed


def test_equal_nonfinite_results_do_not_pass_formal_comparison():
    result = compare_formal_values([np.nan, np.inf], [np.nan, np.inf])
    assert result['mismatches'] == 0
    assert result['reference_nonfinite'] == result['candidate_nonfinite'] == 2
    assert not comparison_passed(result)


def test_comparison_reports_missing_status_and_numeric_difference():
    result = compare_formal_values([1., np.nan, 3.], [2., 2., 3.])
    assert result['mismatches'] == 1
    assert result['finite_status_mismatches'] == 1
    assert not comparison_passed(result)
    assert comparison_passed(compare_formal_values([1., 2.], [1., 2.]))


def test_comparison_rejects_empty_and_mismatched_shapes():
    with pytest.raises(ValueError, match='equal nonempty'):
        compare_formal_values([], [])
    with pytest.raises(ValueError, match='equal nonempty'):
        compare_formal_values([1.], [1., 2.])


def test_asof_audit_never_reads_a_future_sample_and_checks_between_samples():
    from tests.benchmarks.verify_paper_batch_stream import causal_sample_to_source
    np.testing.assert_equal(causal_sample_to_source([3,6],[10.,20.],[1,2,3,4,5,6,7]),[np.nan,np.nan,10.,10.,10.,20.,20.])
    prefix=causal_sample_to_source([3],[10.],[1,2,3,4,5])
    full=causal_sample_to_source([3,6],[10.,20.],[1,2,3,4,5])
    np.testing.assert_equal(prefix,full)
    with pytest.raises(ValueError,match='strictly increasing'):
        causal_sample_to_source([3,3],[10,20],[3])
