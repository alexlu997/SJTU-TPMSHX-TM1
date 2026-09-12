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
