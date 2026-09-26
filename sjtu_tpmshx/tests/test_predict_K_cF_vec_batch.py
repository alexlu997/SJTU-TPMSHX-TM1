"""Fixed-model vector evaluation must preserve scalar values and broadcasting."""
import numpy as np
import pytest


@pytest.fixture(scope="module")
def gyroid_model():
    """Use the unchanged fixed CFD model as the independent scalar reference."""
    from sjtu_tpmshx.df_surrogate.full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2
    return FullCore3CellFixedDFV2('Gyroid')


def _loop_reference(model, L_arr, t_arr, e_arr):
    """Per-cell loop reference — what the OLD predict_K_cF_vec did internally."""
    shape = np.broadcast(L_arr, t_arr, e_arr).shape
    Lf = np.broadcast_to(L_arr, shape).ravel()
    tf = np.broadcast_to(t_arr, shape).ravel()
    ef = np.broadcast_to(e_arr, shape).ravel()
    K = np.empty(Lf.size)
    cF = np.empty(Lf.size)
    for i in range(Lf.size):
        K[i], cF[i] = model.predict(float(Lf[i]), float(tf[i]), float(ef[i]))
    return K.reshape(shape), cF.reshape(shape)


@pytest.mark.parametrize("shape", [
    (5,),         # 1D small
    (12,),        # 1D Shanghai-row
    (4, 3),       # 2D field
    (6, 8, 2),    # 3D tile
])
def test_batched_matches_loop_bit_exact(gyroid_model, shape):
    """Batched implementation must agree with per-cell loop to within rtol=1e-12."""
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec
    rng = np.random.default_rng(seed=42)
    L = rng.uniform(4.5, 7.5, size=shape)
    t = rng.uniform(0.3, 0.5, size=shape)
    e = rng.uniform(0.30, 0.45, size=shape)

    K_loop, cF_loop = _loop_reference(gyroid_model, L, t, e)
    K_batch, cF_batch = predict_K_cF_vec('Gyroid', L, t, e, method='cfd_full_core_3cell_fixed_v2')

    assert K_batch.shape == shape, f"K shape {K_batch.shape} != {shape}"
    assert cF_batch.shape == shape, f"cF shape {cF_batch.shape} != {shape}"
    np.testing.assert_allclose(K_batch, K_loop, rtol=1e-12,
                               err_msg=f"K mismatch at shape {shape}")
    np.testing.assert_allclose(cF_batch, cF_loop, rtol=1e-12,
                               err_msg=f"cF mismatch at shape {shape}")




def test_scalar_broadcast_to_array():
    """Mixed scalar/array inputs broadcast (existing API contract)."""
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec
    K, cF = predict_K_cF_vec('Gyroid',
                              L_mm=np.array([5.0, 6.0, 7.0]),
                              t_mm=0.4,
                              eps_f=0.4)
    assert K.shape == (3,)
    assert cF.shape == (3,)
    assert np.all(K > 0)
    assert np.all(cF > 0)


def test_diamond_path_also_works():
    """Confirm both TPMS types still go through the batched path."""
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec
    K, cF = predict_K_cF_vec('Diamond',
                              np.array([5.0, 6.0]),
                              np.array([0.3, 0.4]),
                              np.array([0.35, 0.40]))
    assert K.shape == (2,)
    assert cF.shape == (2,)
    assert np.all(K > 0)
    assert np.all(cF > 0)


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_batch_preserves_nodes_and_asymmetric_tolerance(topology):
    from sjtu_tpmshx.df_surrogate._domain import TRAIN_L_NODES, TRAIN_T_NODES
    from sjtu_tpmshx.df_surrogate.full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2, METHOD
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec

    pairs = [(L, t) for L in TRAIN_L_NODES for t in TRAIN_T_NODES]
    for axis, nodes in enumerate((TRAIN_L_NODES, TRAIN_T_NODES)):
        for node in nodes:
            for offset in (-2., -.5, .5, 2.):
                if ((node == nodes[0] and offset < -1)
                        or (node == nodes[-1] and offset > 1)):
                    continue  # Out-of-domain errors are checked separately.
                pair = [6.25, .45]
                pair[axis] = node + offset * 1e-12 * max(1., abs(node))
                pairs.append(pair)
    L, t = np.asarray(pairs).T
    expected = _loop_reference(FullCore3CellFixedDFV2(topology), L, t, .35)
    actual = predict_K_cF_vec(topology, L, t, .35, method=METHOD)
    for result, reference in zip(actual, expected):
        np.testing.assert_array_equal(result, reference)


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_batch_preserves_existing_nonfinite_behavior(topology):
    """Compatibility only: nonfinite inputs do not gain physical validity."""
    from sjtu_tpmshx.df_surrogate.full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2, METHOD
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec

    L = np.array([np.nan, np.inf, -np.inf, 6., 6., 6., 6.])
    t = np.array([.4, .4, .4, np.nan, np.inf, -np.inf, .4])
    eps = np.array([.35, .35, .35, .35, np.nan, np.inf, -np.inf])
    expected = _loop_reference(FullCore3CellFixedDFV2(topology), L, t, eps)
    actual = predict_K_cF_vec(topology, L, t, eps, method=METHOD)
    for result, reference in zip(actual, expected):
        np.testing.assert_array_equal(result, reference)


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('L,t,eps', [
    pytest.param(6., .4, .35, id='scalar'),
    pytest.param(np.array(6.), np.array(.4), np.array(.35), id='zero-dimensional'),
    pytest.param(np.empty((0, 3)), .4, .35, id='empty'),
    pytest.param(8.1, np.empty((0, 3)), .35, id='empty-unused-outside'),
    pytest.param(np.array([[4.], [8.]], dtype=np.float32),
                 np.array([.3, .4, .6]), np.ones((4, 1, 1), dtype=int),
                 id='broadcast-and-dtypes'),
    pytest.param(np.linspace(4., 8., 9)[::-2], np.linspace(.3, .6, 10)[::2],
                 .35, id='noncontiguous'),
])
def test_batch_shapes_and_independent_writable_outputs(topology, L, t, eps):
    from sjtu_tpmshx.df_surrogate.full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2, METHOD
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec

    inputs = [value for value in (L, t, eps) if isinstance(value, np.ndarray)]
    originals = [value.copy() for value in inputs]
    expected = _loop_reference(FullCore3CellFixedDFV2(topology), L, t, eps)
    K, cF = predict_K_cF_vec(topology, L, t, eps, method=METHOD)
    for result, reference in zip((K, cF), expected):
        assert result.shape == np.broadcast(L, t, eps).shape
        assert result.dtype == np.float64
        assert result.flags.writeable
        assert all(not np.shares_memory(result, value) for value in inputs)
        np.testing.assert_array_equal(result, reference)
    assert not np.shares_memory(K, cF)
    K[...] = -1.
    np.testing.assert_array_equal(cF, expected[1])
    cF[...] = -2.
    for value, original in zip(inputs, originals):
        np.testing.assert_array_equal(value, original)
    for result, reference in zip(
            predict_K_cF_vec(topology, L, t, eps, method=METHOD), expected):
        np.testing.assert_array_equal(result, reference)


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('L,t', [
    (4. - 8e-12, .4), (8. + 16e-12, .4),
    (6., .3 - 2e-12), (6., .6 + 2e-12),
])
def test_batch_outside_tolerance_preserves_scalar_error(topology, L, t):
    from sjtu_tpmshx.df_surrogate.full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2, METHOD
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec

    lengths, thicknesses = np.array([6., L]), np.array([.4, t])
    with pytest.raises(ValueError) as scalar_error:
        _loop_reference(FullCore3CellFixedDFV2(topology), lengths, thicknesses, .35)
    with pytest.raises(ValueError) as batch_error:
        predict_K_cF_vec(topology, lengths, thicknesses, .35, method=METHOD)
    assert str(batch_error.value) == str(scalar_error.value)


@pytest.mark.parametrize('topology,L,t,method,message', [
    ('Gyroid', [6.], .4, 'retired', "unknown DF method 'retired'"),
    ('Other', [6.], .4, 'cfd_full_core_3cell_fixed_v2', 'support Diamond/Gyroid only'),
    ('Gyroid', np.ones(2), np.ones(3), 'retired', 'shape mismatch'),
    ('Gyroid', ['invalid'], .4, 'retired', 'could not convert string to float'),
])
def test_batch_errors_preserve_validation_order(topology, L, t, method, message):
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec

    with pytest.raises(ValueError, match=message):
        predict_K_cF_vec(topology, L, t, .35, method=method)
