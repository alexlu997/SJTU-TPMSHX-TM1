#pragma once
// Narrow original-algorithm excerpts. PyAMG: Copyright (c) 2008-2015 PyAMG
// Developers (MIT). SciPy: Copyright (c) 2001-2002 Enthought, Inc. 2003, SciPy
// Developers (BSD-3-Clause). Full notices and source revisions are in
// native/licenses/{pyamg-v5.3.0,scipy-v1.17.1}-LICENSE.txt and classical-amg-sources.md.
// Changes: private namespace, unused binding-size attributes, and NumPy integer
// aliases mapped to std::ptrdiff_t. Numerical operations and order are retained.
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <functional>
#include <limits>
#include <stdexcept>
#include <vector>

namespace tpmshx::classical_detail::original {
constexpr int F_NODE=0,C_NODE=1,U_NODE=2,PRE_F_NODE=3;
template<class T> T mynorm(T value) { return std::abs(value); }
template<class T> int signof(T value) { return (T(0)<value)-(value<T(0)); }

// pyamg-v5.3.0/pyamg/amg_core/ruge_stuben.h:63-111
template<class I, class T, class F>
void classical_strength_of_connection_abs(const I n_row,
                                          const F theta,
                                          const I Ap[], [[maybe_unused]] const int Ap_size,
                                          const I Aj[], [[maybe_unused]] const int Aj_size,
                                          const T Ax[], [[maybe_unused]] const int Ax_size,
                                                I Sp[], [[maybe_unused]] const int Sp_size,
                                                I Sj[], [[maybe_unused]] const int Sj_size,
                                                T Sx[], [[maybe_unused]] const int Sx_size)
{
    I nnz = 0;
    Sp[0] = 0;

    for(I i = 0; i < n_row; i++){
        F max_offdiagonal = std::numeric_limits<F>::min();

        const I row_start = Ap[i];
        const I row_end   = Ap[i+1];

        for(I jj = row_start; jj < row_end; jj++){
            if(Aj[jj] != i){
                max_offdiagonal = std::max(max_offdiagonal, mynorm(Ax[jj]));
            }
        }

        F threshold = theta*max_offdiagonal;
        for(I jj = row_start; jj < row_end; jj++){
            F norm_jj = mynorm(Ax[jj]);

            // Add entry if it exceeds the threshold
            if(norm_jj >= threshold){
                if(Aj[jj] != i){
                    Sj[nnz] = Aj[jj];
                    Sx[nnz] = Ax[jj];
                    nnz++;
                }
            }

            // Always add the diagonal
            if(Aj[jj] == i){
                Sj[nnz] = Aj[jj];
                Sx[nnz] = Ax[jj];
                nnz++;
            }
        }

        Sp[i+1] = nnz;
    }
}

// pyamg-v5.3.0/pyamg/amg_core/ruge_stuben.h:284-463
template<class I>
void rs_cf_splitting(const I n_nodes,
                     const I Sp[], [[maybe_unused]] const int Sp_size,
                     const I Sj[], [[maybe_unused]] const int Sj_size,
                     const I Tp[], [[maybe_unused]] const int Tp_size,
                     const I Tj[], [[maybe_unused]] const int Tj_size,
                     const I influence[], [[maybe_unused]] const int influence_size,
                           I splitting[], [[maybe_unused]] const int splitting_size)
{
    std::vector<I> lambda(n_nodes,0);

    // Compute initial lambda based on C^T
    I lambda_max = 0;
    for (I i = 0; i < n_nodes; i++) {
        lambda[i] = Tp[i+1] - Tp[i] + influence[i];
        if (lambda[i] > lambda_max) {
            lambda_max = lambda[i];
        }
    }

    // For each value of lambda, create an interval of nodes with that value
    //      interval_ptr - the first index of the interval
    //      interval_count - the number of indices in that interval
    //      index_to_node - the node located at a given index
    //      node_to_index - the index of a given node
    lambda_max = lambda_max*2;
    if (n_nodes+1 > lambda_max) {
        lambda_max = n_nodes+1;
    }

    std::vector<I> interval_ptr(lambda_max,0);
    std::vector<I> interval_count(lambda_max,0);
    std::vector<I> index_to_node(n_nodes);
    std::vector<I> node_to_index(n_nodes);

    for (I i = 0; i < n_nodes; i++) {
        interval_count[lambda[i]]++;
    }
    for (I i = 0, cumsum = 0; i < lambda_max; i++) {
        interval_ptr[i] = cumsum;
        cumsum += interval_count[i];
        interval_count[i] = 0;
    }
    for (I i = 0; i < n_nodes; i++) {
        I lambda_i = lambda[i];

        I index    = interval_ptr[lambda_i] + interval_count[lambda_i];
        index_to_node[index] = i;
        node_to_index[i]     = index;
        interval_count[lambda_i]++;
    }

    std::fill(splitting, splitting + n_nodes, U_NODE);

    // All nodes with no neighbors become F nodes
    for (I i = 0; i < n_nodes; i++) {
        if (lambda[i] == 0 || (lambda[i] == 1 && Tj[Tp[i]] == i))
            splitting[i] = F_NODE;
    }

    // Add elements to C and F, in descending order of lambda
    for (I top_index=(n_nodes - 1); top_index>-1; top_index--) {

        I i        = index_to_node[top_index];
        I lambda_i = lambda[i];

        // Remove i from its interval
        interval_count[lambda_i]--;

        // ----------------- Sorting every iteration = O(n^2) complexity ----------------- //
        // Search over this interval to make sure we process nodes in descending node order
        // I max_node = i;
        // I max_index = top_index;
        // for (I j = interval_ptr[lambda_i]; j < interval_ptr[lambda_i] + interval_count[lambda_i]; j++) {
        //     if (index_to_node[j] > max_node) {
        //         max_node = index_to_node[j];
        //         max_index = j;
        //     }
        // }
        // node_to_index[index_to_node[top_index]] = max_index;
        // node_to_index[index_to_node[max_index]] = top_index;
        // std::swap(index_to_node[top_index], index_to_node[max_index]);
        // i = index_to_node[top_index];

        // If maximum lambda = 0, break out of loop
        if (lambda[i] <= 0) {
            break;
        }

        // If node is unmarked, set maximum node as C-node and modify
        // lambda values in neighborhood
        if ( splitting[i] == U_NODE) {
            splitting[i] = C_NODE;

            // For each j in S^T_i /\ U, mark j as tentative F-point
            for (I jj = Tp[i]; jj < Tp[i+1]; jj++) {
                I j = Tj[jj];
                if(splitting[j] == U_NODE) {
                    splitting[j] = PRE_F_NODE;
                }
            }

            // For each j in S^T_i /\ U marked as tentative F-point, modify lambda
            // values for neighborhood of j
            for (I jj = Tp[i]; jj < Tp[i+1]; jj++)
            {
                I j = Tj[jj];
                if(splitting[j] == PRE_F_NODE)
                {
                    splitting[j] = F_NODE;

                    // For each k in S_j /\ U, modify lambda value, lambda_k += 1
                    for (I kk = Sp[j]; kk < Sp[j+1]; kk++){
                        I k = Sj[kk];

                        if(splitting[k] == U_NODE){

                            // Move k to the end of its current interval
                            if(lambda[k] >= n_nodes - 1) {
                                continue;
                            }

                            I lambda_k = lambda[k];
                            I old_pos  = node_to_index[k];
                            I new_pos  = interval_ptr[lambda_k] + interval_count[lambda_k] - 1;

                            node_to_index[index_to_node[old_pos]] = new_pos;
                            node_to_index[index_to_node[new_pos]] = old_pos;
                            std::swap(index_to_node[old_pos], index_to_node[new_pos]);

                            // Update intervals
                            interval_count[lambda_k]   -= 1;
                            interval_count[lambda_k+1] += 1; //invalid write!
                            interval_ptr[lambda_k+1]    = new_pos;

                            // Increment lambda_k
                            lambda[k]++;
                        }
                    }
                }
            }

            // For each j in S_i /\ U, set lambda_j -= 1
            for (I jj = Sp[i]; jj < Sp[i+1]; jj++) {
                I j = Sj[jj];
                // Decrement lambda for node j
                if (splitting[j] == U_NODE) {
                    if (lambda[j] == 0) {
                        continue;
                    }

                    // Move j to the beginning of its current interval
                    I lambda_j = lambda[j];
                    I old_pos  = node_to_index[j];
                    I new_pos  = interval_ptr[lambda_j];

                    node_to_index[index_to_node[old_pos]] = new_pos;
                    node_to_index[index_to_node[new_pos]] = old_pos;
                    std::swap(index_to_node[old_pos],index_to_node[new_pos]);

                    // Update intervals
                    interval_count[lambda_j]   -= 1;
                    interval_count[lambda_j-1] += 1;
                    interval_ptr[lambda_j]     += 1;
                    interval_ptr[lambda_j-1]    = interval_ptr[lambda_j] - interval_count[lambda_j-1];

                    // Decrement lambda_j
                    lambda[j]--;
                }
            }
        }
    }

    // Set any unmarked nodes as F-points
    for (I i=0; i<n_nodes; i++) {
        if (splitting[i] == U_NODE) {
            splitting[i] = F_NODE;
        }
    }
}

// pyamg-v5.3.0/pyamg/amg_core/ruge_stuben.h:1082-1103
template<class I>
void rs_classical_interpolation_pass1(const I n_nodes,
                                      const I Sp[], [[maybe_unused]] const int Sp_size,
                                      const I Sj[], [[maybe_unused]] const int Sj_size,
                                      const I splitting[], [[maybe_unused]] const int splitting_size,
                                            I Pp[], [[maybe_unused]] const int Pp_size)
{
    I nnz = 0;
    Pp[0] = 0;
    for (I i = 0; i < n_nodes; i++){
        if( splitting[i] == C_NODE ){
            nnz++;
        }
        else {
            for (I jj = Sp[i]; jj < Sp[i+1]; jj++){
                if ( (splitting[Sj[jj]] == C_NODE) && (Sj[jj] != i) )
                    nnz++;
            }
        }
        Pp[i+1] = nnz;
    }
}

// pyamg-v5.3.0/pyamg/amg_core/ruge_stuben.h:1132-1181
template<class I, class T>
void remove_strong_FF_connections(const I n_nodes,
                                  const I Sp[], [[maybe_unused]] const int Sp_size,
                                  const I Sj[], [[maybe_unused]] const int Sj_size,
                                        T Sx[], [[maybe_unused]] const int Sx_size,
                                  const I splitting[], [[maybe_unused]] const int splitting_size)
{
    // For each F-point
    for (I row=0; row<n_nodes; row++) {
        if (splitting[row] == F_NODE) {

            // For each j in S_row /\ F, test dependence of j on S_row /\ C
            for (I jj=Sp[row]; jj<Sp[row+1]; jj++) {
                I j = Sj[jj];

                if (splitting[j] == F_NODE) {

                    // Test dependence, i.e. check that S_j /\ S_row /\ C is
                    // nonempty. This is simply checking that nodes j and row
                    // have a common strong C-point connection.
                    bool dependence = false;
                    for (I ii=Sp[row]; ii<Sp[row+1]; ii++) {
                        I row_ind = Sj[ii];
                        if (splitting[row_ind] == C_NODE) {
                            for (I kk=Sp[j]; kk<Sp[j+1]; kk++) {
                                if (Sj[kk] == row_ind) {
                                    dependence = true;
                                }
                            }
                        }
                        if (dependence) {
                            break;
                        }
                    }

                    // Node j passed dependence test
                    if (dependence) {
                        continue;
                    }
                    // Node j did not pass dependence test. That is, the two F-points
                    // do not have a common C neighbor, and we thus remove the strong
                    // connection.
                    else {
                        Sx[jj] = 0;
                    }
                }
            }
        }
    }
}

// pyamg-v5.3.0/pyamg/amg_core/ruge_stuben.h:1238-1383
template<class I, class T>
void rs_classical_interpolation_pass2(const I n_nodes,
                                      const I Ap[], [[maybe_unused]] const int Ap_size,
                                      const I Aj[], [[maybe_unused]] const int Aj_size,
                                      const T Ax[], [[maybe_unused]] const int Ax_size,
                                      const I Sp[], [[maybe_unused]] const int Sp_size,
                                      const I Sj[], [[maybe_unused]] const int Sj_size,
                                      const T Sx[], [[maybe_unused]] const int Sx_size,
                                      const I splitting[], [[maybe_unused]] const int splitting_size,
                                      const I Pp[], [[maybe_unused]] const int Pp_size,
                                            I Pj[], [[maybe_unused]] const int Pj_size,
                                            T Px[], [[maybe_unused]] const int Px_size,
                                      const bool modified)
{
    for (I i = 0; i < n_nodes; i++) {
        // If node i is a C-point, then set interpolation as injection
        if(splitting[i] == C_NODE) {
            Pj[Pp[i]] = i;
            Px[Pp[i]] = 1;
        }
        // Otherwise, use RS classical interpolation formula
        else {

            // Calculate denominator
            T denominator = 0;

            // Start by summing entire row of A
            for (I mm = Ap[i]; mm < Ap[i+1]; mm++) {
                denominator += Ax[mm];
            }

            // Then subtract off the strong connections so that you are left with
            // denominator = a_ii + sum_{m in weak connections} a_im
            for (I mm = Sp[i]; mm < Sp[i+1]; mm++) {
                if ( Sj[mm] != i ) {
                    denominator -= Sx[mm]; // making sure to leave the diagonal entry in there
                }
            }

            // Set entries in P (interpolation weights w_ij from strongly connected C-points)
            I nnz = Pp[i];
            for (I jj = Sp[i]; jj < Sp[i+1]; jj++) {

                if (splitting[Sj[jj]] == C_NODE) {

                    // Set temporary value for Pj as global index, j. Will be mapped to
                    // appropriate coarse-grid column index after all data is filled in.
                    Pj[nnz] = Sj[jj];
                    I j = Sj[jj];

                    // Initialize numerator as a_ij
                    T numerator = Sx[jj];

                    // Sum over strongly connected fine points
                    for (I kk = Sp[i]; kk < Sp[i+1]; kk++) {
                        if ( (splitting[Sj[kk]] == F_NODE) && (Sj[kk] != i) ) {

                            // Get column k and value a_ik
                            I k = Sj[kk];
                            T a_ik = Sx[kk];

                            // Get a_kj (have to search over k'th row in A for connection a_kj)
                            T a_kj = 0;
                            T a_kk = 0;
                            if (modified) {
                                for (I search_ind = Ap[k]; search_ind < Ap[k+1]; search_ind++) {
                                    if (Aj[search_ind] == j) {
                                        a_kj = Ax[search_ind];
                                    }
                                    else if (Aj[search_ind] == k) {
                                        a_kk = Ax[search_ind];
                                    }
                                }
                            }
                            else {
                                for (I search_ind = Ap[k]; search_ind < Ap[k+1]; search_ind++) {
                                    if ( Aj[search_ind] == j ) {
                                        a_kj = Ax[search_ind];
                                        break;
                                    }
                                }
                            }

                            // If sign of a_kj matches sign of a_kk, ignore a_kj in sum
                            // (i.e. leave as a_kj = 0) for modified interpolation
                            if ( modified && (signof(a_kj) == signof(a_kk)) ) {
                                a_kj = 0;
                            }

                            // If a_kj == 0, then we don't need to do any more work, otherwise
                            // proceed to account for node k's contribution
                            if (std::abs(a_kj) > 1e-15*std::abs(a_ik)) {

                                // Calculate sum for inner denominator (loop over strongly connected C-points)
                                T inner_denominator = 0;
                                for (I ll = Sp[i]; ll < Sp[i+1]; ll++) {
                                    if (splitting[Sj[ll]] == C_NODE) {

                                        // Get column l
                                        I l = Sj[ll];

                                        // Add connection a_kl if present in matrix (search over kth row in A for connection)
                                        // Only add if sign of a_kl does not equal sign of a_kk
                                        for (I search_ind = Ap[k]; search_ind < Ap[k+1]; search_ind++) {
                                            if (Aj[search_ind] == l) {
                                                T a_kl = Ax[search_ind];
                                                if ( (!modified) || (signof(a_kl) != signof(a_kk)) ) {
                                                    inner_denominator += a_kl;
                                                }
                                                break;
                                            }
                                        }
                                    }
                                }

                                // Add a_ik * a_kj / inner_denominator to the numerator
                                if (std::abs(inner_denominator) < 1e-15*std::abs(a_ik * a_kj)) {
                                    printf("Inner denominator was zero.\n");
                                }
                                numerator += a_ik * a_kj / inner_denominator;
                            }
                        }
                    }

                    // Set w_ij = -numerator/denominator
                    if (std::abs(denominator) < 1e-15*std::abs(numerator)) {
                        printf("Outer denominator was zero: diagonal plus sum of weak connections was zero.\n");
                    }
                    Px[nnz] = -numerator / denominator;
                    nnz++;
                }
            }
        }
    }

    // Column indices were initially stored as global indices. Build map to switch
    // to C-point indices.
    std::vector<I> map(n_nodes);
    for (I i = 0, sum = 0; i < n_nodes; i++) {
        map[i]  = sum;
        sum    += splitting[i];
    }
    for (I i = 0; i < Pp[n_nodes]; i++) {
        Pj[i] = map[Pj[i]];
    }
}

// pyamg-v5.3.0/pyamg/amg_core/relaxation.h:48-76
template<class I, class T, class F>
void gauss_seidel(const I Ap[], [[maybe_unused]] const int Ap_size,
                  const I Aj[], [[maybe_unused]] const int Aj_size,
                  const T Ax[], [[maybe_unused]] const int Ax_size,
                        T  x[], [[maybe_unused]] const int x_size,
                  const T  b[], [[maybe_unused]] const int b_size,
                  const I row_start,
                  const I row_stop,
                  const I row_step)
{
    for(I i = row_start; i != row_stop; i += row_step) {
        I start = Ap[i];
        I end   = Ap[i+1];
        T rsum = 0;
        T diag = 0;

        for(I jj = start; jj < end; jj++){
            I j = Aj[jj];
            if (i == j)
                diag  = Ax[jj];
            else
                rsum += Ax[jj]*x[j];
        }

        if (diag != (F) 0.0){
            x[i] = (b[i] - rsum)/diag;
        }
    }
}

// scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:325-340
template <class I>
bool csr_has_canonical_format(const I n_row,
                              const I Ap[],
                              const I Aj[])
{
    for(I i = 0; i < n_row; i++){
        if (Ap[i] > Ap[i+1])
            return false;
        for(I jj = Ap[i] + 1; jj < Ap[i+1]; jj++){
            if( !(Aj[jj-1] < Aj[jj]) ){
                return false;
            }
        }
    }
    return true;
}

// scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:418-462
template <class I, class T>
void csr_tocsc(const I n_row,
               const I n_col,
               const I Ap[],
               const I Aj[],
               const T Ax[],
                     I Bp[],
                     I Bi[],
                     T Bx[])
{
    const I nnz = Ap[n_row];

    //compute number of non-zero entries per column of A
    std::fill(Bp, Bp + n_col, 0);

    for (I n = 0; n < nnz; n++){
        Bp[Aj[n]]++;
    }

    //cumsum the nnz per column to get Bp[]
    for(I col = 0, cumsum = 0; col < n_col; col++){
        I temp  = Bp[col];
        Bp[col] = cumsum;
        cumsum += temp;
    }
    Bp[n_col] = nnz;

    for(I row = 0; row < n_row; row++){
        for(I jj = Ap[row]; jj < Ap[row+1]; jj++){
            I col  = Aj[jj];
            I dest = Bp[col];

            Bi[dest] = row;
            Bx[dest] = Ax[jj];

            Bp[col]++;
        }
    }

    for(I col = 0, last = 0; col <= n_col; col++){
        I temp  = Bp[col];
        Bp[col] = last;
        last    = temp;
    }
}

// scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:562-601
template <class I>
std::ptrdiff_t csr_matmat_maxnnz(const I n_row,
                           const I n_col,
                           const I Ap[],
                           const I Aj[],
                           const I Bp[],
                           const I Bj[])
{
    // method that uses O(n) temp storage
    std::vector<I> mask(n_col, -1);

    std::ptrdiff_t nnz = 0;
    for(I i = 0; i < n_row; i++){
        std::ptrdiff_t row_nnz = 0;

        for(I jj = Ap[i]; jj < Ap[i+1]; jj++){
            I j = Aj[jj];
            for(I kk = Bp[j]; kk < Bp[j+1]; kk++){
                I k = Bj[kk];
                if(mask[k] != i){
                    mask[k] = i;
                    row_nnz++;
                }
            }
        }

        std::ptrdiff_t next_nnz = nnz + row_nnz;

        if (row_nnz > std::numeric_limits<std::ptrdiff_t>::max() - nnz) {
            /*
             * Index overflowed. Note that row_nnz <= n_col and cannot overflow
             */
            throw std::overflow_error("nnz of the result is too large");
        }

        nnz = next_nnz;
    }

    return nnz;
}

// scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:607-669
template <class I, class T>
void csr_matmat(const I n_row,
                const I n_col,
                const I Ap[],
                const I Aj[],
                const T Ax[],
                const I Bp[],
                const I Bj[],
                const T Bx[],
                      I Cp[],
                      I Cj[],
                      T Cx[])
{
    std::vector<I> next(n_col,-1);
    std::vector<T> sums(n_col, 0);

    I nnz = 0;

    Cp[0] = 0;

    for(I i = 0; i < n_row; i++){
        I head   = -2;
        I length =  0;

        I jj_start = Ap[i];
        I jj_end   = Ap[i+1];
        for(I jj = jj_start; jj < jj_end; jj++){
            I j = Aj[jj];
            T v = Ax[jj];

            I kk_start = Bp[j];
            I kk_end   = Bp[j+1];
            for(I kk = kk_start; kk < kk_end; kk++){
                I k = Bj[kk];

                sums[k] += v*Bx[kk];

                if(next[k] == -1){
                    next[k] = head;
                    head  = k;
                    length++;
                }
            }
        }

        for(I jj = 0; jj < length; jj++){

            if(sums[head] != 0){
                Cj[nnz] = head;
                Cx[nnz] = sums[head];
                nnz++;
            }

            I temp = head;
            head = next[head];

            next[temp] = -1; //clear arrays
            sums[temp] =  0;
        }

        Cp[i+1] = nnz;
    }
}

// scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:691-763
template <class I, class T, class T2, class binary_op>
void csr_binop_csr_general(const I n_row, const I n_col,
                           const I Ap[], const I Aj[], const T Ax[],
                           const I Bp[], const I Bj[], const T Bx[],
                                 I Cp[],       I Cj[],       T2 Cx[],
                           const binary_op& op)
{
    //Method that works for duplicate and/or unsorted indices

    std::vector<I>  next(n_col,-1);
    std::vector<T> A_row(n_col, 0);
    std::vector<T> B_row(n_col, 0);

    I nnz = 0;
    Cp[0] = 0;

    for(I i = 0; i < n_row; i++){
        I head   = -2;
        I length =  0;

        //add a row of A to A_row
        I i_start = Ap[i];
        I i_end   = Ap[i+1];
        for(I jj = i_start; jj < i_end; jj++){
            I j = Aj[jj];

            A_row[j] += Ax[jj];

            if(next[j] == -1){
                next[j] = head;
                head = j;
                length++;
            }
        }

        //add a row of B to B_row
        i_start = Bp[i];
        i_end   = Bp[i+1];
        for(I jj = i_start; jj < i_end; jj++){
            I j = Bj[jj];

            B_row[j] += Bx[jj];

            if(next[j] == -1){
                next[j] = head;
                head = j;
                length++;
            }
        }


        // scan through columns where A or B has
        // contributed a non-zero entry
        for(I jj = 0; jj < length; jj++){
            T result = op(A_row[head], B_row[head]);

            if(result != 0){
                Cj[nnz] = head;
                Cx[nnz] = result;
                nnz++;
            }

            I temp = head;
            head = next[head];

            next[temp]  = -1;
            A_row[temp] =  0;
            B_row[temp] =  0;
        }

        Cp[i + 1] = nnz;
    }
}

// scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:781-855
template <class I, class T, class T2, class binary_op>
void csr_binop_csr_canonical(const I n_row, [[maybe_unused]] const I n_col,
                             const I Ap[], const I Aj[], const T Ax[],
                             const I Bp[], const I Bj[], const T Bx[],
                                   I Cp[],       I Cj[],       T2 Cx[],
                             const binary_op& op)
{
    //Method that works for canonical CSR matrices

    Cp[0] = 0;
    I nnz = 0;

    for(I i = 0; i < n_row; i++){
        I A_pos = Ap[i];
        I B_pos = Bp[i];
        I A_end = Ap[i+1];
        I B_end = Bp[i+1];

        //while not finished with either row
        while(A_pos < A_end && B_pos < B_end){
            I A_j = Aj[A_pos];
            I B_j = Bj[B_pos];

            if(A_j == B_j){
                T result = op(Ax[A_pos],Bx[B_pos]);
                if(result != 0){
                    Cj[nnz] = A_j;
                    Cx[nnz] = result;
                    nnz++;
                }
                A_pos++;
                B_pos++;
            } else if (A_j < B_j) {
                T result = op(Ax[A_pos],0);
                if (result != 0){
                    Cj[nnz] = A_j;
                    Cx[nnz] = result;
                    nnz++;
                }
                A_pos++;
            } else {
                //B_j < A_j
                T result = op(0,Bx[B_pos]);
                if (result != 0){
                    Cj[nnz] = B_j;
                    Cx[nnz] = result;
                    nnz++;
                }
                B_pos++;
            }
        }

        //tail
        while(A_pos < A_end){
            T result = op(Ax[A_pos],0);
            if (result != 0){
                Cj[nnz] = Aj[A_pos];
                Cx[nnz] = result;
                nnz++;
            }
            A_pos++;
        }
        while(B_pos < B_end){
            T result = op(0,Bx[B_pos]);
            if (result != 0){
                Cj[nnz] = Bj[B_pos];
                Cx[nnz] = result;
                nnz++;
            }
            B_pos++;
        }

        Cp[i+1] = nnz;
    }
}

// scipy-v1.17.1/scipy/sparse/sparsetools/csr.h:889-907
template <class I, class T, class T2, class binary_op>
void csr_binop_csr(const I n_row,
                   const I n_col,
                   const I Ap[],
                   const I Aj[],
                   const T Ax[],
                   const I Bp[],
                   const I Bj[],
                   const T Bx[],
                         I Cp[],
                         I Cj[],
                         T2 Cx[],
                   const binary_op& op)
{
    if (csr_has_canonical_format(n_row,Ap,Aj) && csr_has_canonical_format(n_row,Bp,Bj))
        csr_binop_csr_canonical(n_row, n_col, Ap, Aj, Ax, Bp, Bj, Bx, Cp, Cj, Cx, op);
    else
        csr_binop_csr_general(n_row, n_col, Ap, Aj, Ax, Bp, Bj, Bx, Cp, Cj, Cx, op);
}

} // namespace tpmshx::classical_detail::original
