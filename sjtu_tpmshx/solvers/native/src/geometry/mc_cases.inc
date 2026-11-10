// Derived from scikit-image 0.26.0. See THIRD_PARTY_NOTICES.md for source and licenses.
int test_face(const Cell& cell, int face);
int test_internal(const Cell& cell, int case_id, int config, int subconfig, int s);
void big_switch(Cell& cell, int case_id, int config) {
    int subconfig = 0;
    if (case_id == 1) {
        cell.add_triangles(lut::TILING1, config, 1);
    }
    else if (case_id == 2) {
        cell.add_triangles(lut::TILING2, config, 2);
    }
    else if (case_id == 3) {
        if (test_face(cell, lut::TEST3.get1(config))) {
            cell.add_triangles(lut::TILING3_2, config, 4);
        }
        else {
            cell.add_triangles(lut::TILING3_1, config, 2);
        }
    }
    else if (case_id == 4) {
        if (test_internal(cell, case_id, config, subconfig, lut::TEST4.get1(config))) {
            cell.add_triangles(lut::TILING4_1, config, 2);
        }
        else {
            cell.add_triangles(lut::TILING4_2, config, 6);
        }
    }
    else if (case_id == 5) {
        cell.add_triangles(lut::TILING5, config, 3);
    }
    else if (case_id == 6) {
        if (test_face(cell, lut::TEST6.get2(config,0))) {
            cell.add_triangles(lut::TILING6_2, config, 5);
        }
        else {
            if (test_internal(cell, case_id, config, subconfig, lut::TEST6.get2(config,1))) {
                cell.add_triangles(lut::TILING6_1_1, config, 3);
            }
            else {
                cell.add_triangles(lut::TILING6_1_2, config, 9);
            }
        }
    }
    else if (case_id == 7) {
        if (test_face(cell, lut::TEST7.get2(config,0))) { subconfig += 1; }
        if (test_face(cell, lut::TEST7.get2(config,1))) { subconfig += 2; }
        if (test_face(cell, lut::TEST7.get2(config,2))) { subconfig += 4; }
        if (subconfig == 0) { cell.add_triangles(lut::TILING7_1, config, 3); }
        else if (subconfig == 1) { cell.add_triangles2(lut::TILING7_2, config, 0, 5); }
        else if (subconfig == 2) { cell.add_triangles2(lut::TILING7_2, config, 1, 5); }
        else if (subconfig == 3) {
            cell.add_triangles2(lut::TILING7_3, config, 0, 9);
        }
        else if (subconfig == 4) { cell.add_triangles2(lut::TILING7_2, config, 2, 5); }
        else if (subconfig == 5) {
            cell.add_triangles2(lut::TILING7_3, config, 1, 9);
        }
        else if (subconfig == 6) {
            cell.add_triangles2(lut::TILING7_3, config, 2, 9);
        }
        else if (subconfig == 7) {
            if (test_internal(cell, case_id, config, subconfig, lut::TEST7.get2(config,3))) {
                cell.add_triangles(lut::TILING7_4_2, config, 9);
            }
            else {
                cell.add_triangles(lut::TILING7_4_1, config, 5);
            }
        }
    }
    else if (case_id == 8) {
        cell.add_triangles(lut::TILING8, config, 2);
    }
    else if (case_id == 9) {
        cell.add_triangles(lut::TILING9, config, 4);
    }
    else if (case_id == 10) {
        if (test_face(cell, lut::TEST10.get2(config,0))) {
            if (test_face(cell, lut::TEST10.get2(config,1))) {
                cell.add_triangles(lut::TILING10_1_1_, config, 4);
            }
            else {
                cell.add_triangles(lut::TILING10_2, config, 8);
            }
        }
        else {
            if (test_face(cell, lut::TEST10.get2(config,1))) {
                cell.add_triangles(lut::TILING10_2_, config, 8);
            }
            else {
                if (test_internal(cell, case_id, config, subconfig, lut::TEST10.get2(config,2))) {
                    cell.add_triangles(lut::TILING10_1_1, config, 4);
                }
                else {
                    cell.add_triangles(lut::TILING10_1_2, config, 8);
                }
            }
        }
    }
    else if (case_id == 11) {
        cell.add_triangles(lut::TILING11, config, 4);
    }
    else if (case_id == 12) {
        if (test_face(cell, lut::TEST12.get2(config,0))) {
            if (test_face(cell, lut::TEST12.get2(config,1))) {
                cell.add_triangles(lut::TILING12_1_1_, config, 4);
            }
            else {
                cell.add_triangles(lut::TILING12_2, config, 8);
            }
        }
        else {
            if (test_face(cell, lut::TEST12.get2(config,1))) {
                cell.add_triangles(lut::TILING12_2_, config, 8);
            }
            else {
                if (test_internal(cell, case_id, config, subconfig, lut::TEST12.get2(config,2))) {
                    cell.add_triangles(lut::TILING12_1_1, config, 4);
                }
                else {
                    cell.add_triangles(lut::TILING12_1_2, config, 8);
                }
            }
        }
    }
    else if (case_id == 13) {
        if (test_face(cell, lut::TEST13.get2(config,0))) { subconfig += 1; }
        if (test_face(cell, lut::TEST13.get2(config,1))) { subconfig += 2; }
        if (test_face(cell, lut::TEST13.get2(config,2))) { subconfig += 4; }
        if (test_face(cell, lut::TEST13.get2(config,3))) { subconfig += 8; }
        if (test_face(cell, lut::TEST13.get2(config,4))) { subconfig += 16; }
        if (test_face(cell, lut::TEST13.get2(config,5))) { subconfig += 32; }
        subconfig = lut::SUBCONFIG13.get1(subconfig);
        if (subconfig==0) { cell.add_triangles(lut::TILING13_1, config, 4); }
        else if (subconfig==1) { cell.add_triangles2(lut::TILING13_2, config, 0, 6); }
        else if (subconfig==2) { cell.add_triangles2(lut::TILING13_2, config, 1, 6); }
        else if (subconfig==3) { cell.add_triangles2(lut::TILING13_2, config, 2, 6); }
        else if (subconfig==4) { cell.add_triangles2(lut::TILING13_2, config, 3, 6); }
        else if (subconfig==5) { cell.add_triangles2(lut::TILING13_2, config, 4, 6); }
        else if (subconfig==6) { cell.add_triangles2(lut::TILING13_2, config, 5, 6); }
        else if (subconfig==7) {
            cell.add_triangles2(lut::TILING13_3, config, 0, 10);
        }
        else if (subconfig==8) {
            cell.add_triangles2(lut::TILING13_3, config, 1, 10);
        }
        else if (subconfig==9) {
            cell.add_triangles2(lut::TILING13_3, config, 2, 10);
        }
        else if (subconfig==10) {
            cell.add_triangles2(lut::TILING13_3, config, 3, 10);
        }
        else if (subconfig==11) {
            cell.add_triangles2(lut::TILING13_3, config, 4, 10);
        }
        else if (subconfig==12) {
            cell.add_triangles2(lut::TILING13_3, config, 5, 10);
        }
        else if (subconfig==13) {
            cell.add_triangles2(lut::TILING13_3, config, 6, 10);
        }
        else if (subconfig==14) {
            cell.add_triangles2(lut::TILING13_3, config, 7, 10);
        }
        else if (subconfig==15) {
            cell.add_triangles2(lut::TILING13_3, config, 8, 10);
        }
        else if (subconfig==16) {
            cell.add_triangles2(lut::TILING13_3, config, 9, 10);
        }
        else if (subconfig==17) {
            cell.add_triangles2(lut::TILING13_3, config, 10, 10);
        }
        else if (subconfig==18) {
            cell.add_triangles2(lut::TILING13_3, config, 11, 10);
        }
        else if (subconfig==19) {
            cell.add_triangles2(lut::TILING13_4, config, 0, 12);
        }
        else if (subconfig==20) {
            cell.add_triangles2(lut::TILING13_4, config, 1, 12);
        }
        else if (subconfig==21) {
            cell.add_triangles2(lut::TILING13_4, config, 2, 12);
        }
        else if (subconfig==22) {
            cell.add_triangles2(lut::TILING13_4, config, 3, 12);
        }
        else if (subconfig==23) {
            subconfig = 0;
            if (test_internal(cell, case_id, config, subconfig, lut::TEST13.get2(config,6))) {
                cell.add_triangles2(lut::TILING13_5_1, config, 0, 6);
            }
            else {
                cell.add_triangles2(lut::TILING13_5_2, config, 0, 10);
            }
        }
        else if (subconfig==24) {
            subconfig = 1;
            if (test_internal(cell, case_id, config, subconfig, lut::TEST13.get2(config,6))) {
                cell.add_triangles2(lut::TILING13_5_1, config, 1, 6);
            }
            else {
                cell.add_triangles2(lut::TILING13_5_2, config, 1, 10);
            }
        }
        else if (subconfig==25) {
            subconfig = 2;
            if (test_internal(cell, case_id, config, subconfig, lut::TEST13.get2(config,6))) {
                cell.add_triangles2(lut::TILING13_5_1, config, 2, 6);
            }
            else {
                cell.add_triangles2(lut::TILING13_5_2, config, 2, 10);
            }
        }
        else if (subconfig==26) {
            subconfig = 3;
            if (test_internal(cell, case_id, config, subconfig, lut::TEST13.get2(config,6))) {
                cell.add_triangles2(lut::TILING13_5_1, config, 3, 6);
            }
            else {
                cell.add_triangles2(lut::TILING13_5_2, config, 3, 10);
            }
        }
        else if (subconfig==27) {
            cell.add_triangles2(lut::TILING13_3_, config, 0, 10);
        }
        else if (subconfig==28) {
            cell.add_triangles2(lut::TILING13_3_, config, 1, 10);
        }
        else if (subconfig==29) {
            cell.add_triangles2(lut::TILING13_3_, config, 2, 10);
        }
        else if (subconfig==30) {
            cell.add_triangles2(lut::TILING13_3_, config, 3, 10);
        }
        else if (subconfig==31) {
            cell.add_triangles2(lut::TILING13_3_, config, 4, 10);
        }
        else if (subconfig==32) {
            cell.add_triangles2(lut::TILING13_3_, config, 5, 10);
        }
        else if (subconfig==33) {
            cell.add_triangles2(lut::TILING13_3_, config,6, 10);
        }
        else if (subconfig==34) {
            cell.add_triangles2(lut::TILING13_3_, config, 7, 10);
        }
        else if (subconfig==35) {
            cell.add_triangles2(lut::TILING13_3_, config, 8, 10);
        }
        else if (subconfig==36) {
            cell.add_triangles2(lut::TILING13_3_, config, 9, 10);
        }
        else if (subconfig==37) {
            cell.add_triangles2(lut::TILING13_3_, config, 10, 10);
        }
        else if (subconfig==38) {
            cell.add_triangles2(lut::TILING13_3_, config, 11, 10);
        }
        else if (subconfig==39) {
            cell.add_triangles2(lut::TILING13_2_, config, 0, 6);
        }
        else if (subconfig==40) {
            cell.add_triangles2(lut::TILING13_2_, config, 1, 6);
        }
        else if (subconfig==41) {
            cell.add_triangles2(lut::TILING13_2_, config, 2, 6);
        }
        else if (subconfig==42) {
            cell.add_triangles2(lut::TILING13_2_, config, 3, 6);
        }
        else if (subconfig==43) {
            cell.add_triangles2(lut::TILING13_2_, config, 4, 6);
        }
        else if (subconfig==44) {
            cell.add_triangles2(lut::TILING13_2_, config, 5, 6);
        }
        else if (subconfig==45) {
            cell.add_triangles(lut::TILING13_1_, config, 4);
        }
        else {
            std::puts("Marching Cubes: Impossible case 13?");
        }
    }
    else if (case_id == 14) {
        cell.add_triangles(lut::TILING14, config, 4);
    }
}

int test_face(const Cell& cell, int face) {
    int absFace = face;
    if (face < 0) {
        absFace *= -1;
    }
    double A=0, B=0, C=0, D=0;
    if (absFace == 1) {
        std::tie(A, B, C, D) = std::make_tuple(cell.v[0], cell.v[4], cell.v[5], cell.v[1]);
    }
    else if (absFace == 2) {
        std::tie(A, B, C, D) = std::make_tuple(cell.v[1], cell.v[5], cell.v[6], cell.v[2]);
    }
    else if (absFace == 3) {
        std::tie(A, B, C, D) = std::make_tuple(cell.v[2], cell.v[6], cell.v[7], cell.v[3]);
    }
    else if (absFace == 4) {
        std::tie(A, B, C, D) = std::make_tuple(cell.v[3], cell.v[7], cell.v[4], cell.v[0]);
    }
    else if (absFace == 5) {
        std::tie(A, B, C, D) = std::make_tuple(cell.v[0], cell.v[3], cell.v[2], cell.v[1]);
    }
    else if (absFace == 6) {
        std::tie(A, B, C, D) = std::make_tuple(cell.v[4], cell.v[7], cell.v[6], cell.v[5]);
    }
    double AC_BD = A*C - B*D;
    if (AC_BD > - epsilon && AC_BD < epsilon) {
        return face >= 0;
    }
    else {
        return face * A * AC_BD >= 0;
    }
}

int test_internal(const Cell& cell, int case_id, int config, int subconfig, int s) {
    double t, At, Bt, Ct, Dt, a, b;
    int test = 0;
    int edge = -1;
    std::tie(At, Bt, Ct, Dt) = std::make_tuple(0.0, 0.0, 0.0, 0.0);
    if (case_id==4 || case_id==10) {
        a = ( cell.v[4] - cell.v[0] ) * ( cell.v[6] - cell.v[2] ) - ( cell.v[7] - cell.v[3] ) * ( cell.v[5] - cell.v[1] );
        b =  cell.v[2] * ( cell.v[4] - cell.v[0] ) + cell.v[0] * ( cell.v[6] - cell.v[2] ) - cell.v[1] * ( cell.v[7] - cell.v[3] ) - cell.v[3] * ( cell.v[5] - cell.v[1] );
        t = - b / (2*a + epsilon);
        if (t<0 || t>1) { return s>0; }
        At = cell.v[0] + ( cell.v[4] - cell.v[0] ) * t;
        Bt = cell.v[3] + ( cell.v[7] - cell.v[3] ) * t;
        Ct = cell.v[2] + ( cell.v[6] - cell.v[2] ) * t;
        Dt = cell.v[1] + ( cell.v[5] - cell.v[1] ) * t;
    }
    else if (case_id==6 || case_id==7 || case_id==12 || case_id==13) {
        if (case_id == 6) { edge = lut::TEST6.get2(config, 2); }
        else if (case_id == 7) { edge = lut::TEST7.get2(config, 4); }
        else if (case_id == 12) { edge = lut::TEST12.get2(config, 3); }
        else if (case_id == 13) { edge = lut::TILING13_5_1.get3(config, subconfig, 0); }
        if (edge==0) {
            t  = cell.v[0] / ( cell.v[0] - cell.v[1] + epsilon );
            At = 0;
            Bt = cell.v[3] + ( cell.v[2] - cell.v[3] ) * t;
            Ct = cell.v[7] + ( cell.v[6] - cell.v[7] ) * t;
            Dt = cell.v[4] + ( cell.v[5] - cell.v[4] ) * t;
        }
        else if (edge==1) {
            t  = cell.v[1] / ( cell.v[1] - cell.v[2] + epsilon );
            At = 0;
            Bt = cell.v[0] + ( cell.v[3] - cell.v[0] ) * t;
            Ct = cell.v[4] + ( cell.v[7] - cell.v[4] ) * t;
            Dt = cell.v[5] + ( cell.v[6] - cell.v[5] ) * t;
        }
        else if (edge==2) {
            t  = cell.v[2] / ( cell.v[2] - cell.v[3] + epsilon );
            At = 0;
            Bt = cell.v[1] + ( cell.v[0] - cell.v[1] ) * t;
            Ct = cell.v[5] + ( cell.v[4] - cell.v[5] ) * t;
            Dt = cell.v[6] + ( cell.v[7] - cell.v[6] ) * t;
        }
        else if (edge==3) {
            t  = cell.v[3] / ( cell.v[3] - cell.v[0] + epsilon );
            At = 0;
            Bt = cell.v[2] + ( cell.v[1] - cell.v[2] ) * t;
            Ct = cell.v[6] + ( cell.v[5] - cell.v[6] ) * t;
            Dt = cell.v[7] + ( cell.v[4] - cell.v[7] ) * t;
        }
        else if (edge==4) {
            t  = cell.v[4] / ( cell.v[4] - cell.v[5] + epsilon );
            At = 0;
            Bt = cell.v[7] + ( cell.v[6] - cell.v[7] ) * t;
            Ct = cell.v[3] + ( cell.v[2] - cell.v[3] ) * t;
            Dt = cell.v[0] + ( cell.v[1] - cell.v[0] ) * t;
        }
        else if (edge==5) {
            t  = cell.v[5] / ( cell.v[5] - cell.v[6] + epsilon );
            At = 0;
            Bt = cell.v[4] + ( cell.v[7] - cell.v[4] ) * t;
            Ct = cell.v[0] + ( cell.v[3] - cell.v[0] ) * t;
            Dt = cell.v[1] + ( cell.v[2] - cell.v[1] ) * t;
        }
        else if (edge==6) {
            t  = cell.v[6] / ( cell.v[6] - cell.v[7] + epsilon );
            At = 0;
            Bt = cell.v[5] + ( cell.v[4] - cell.v[5] ) * t;
            Ct = cell.v[1] + ( cell.v[0] - cell.v[1] ) * t;
            Dt = cell.v[2] + ( cell.v[3] - cell.v[2] ) * t;
        }
        else if (edge==7) {
            t  = cell.v[7] / ( cell.v[7] - cell.v[4] + epsilon );
            At = 0;
            Bt = cell.v[6] + ( cell.v[5] - cell.v[6] ) * t;
            Ct = cell.v[2] + ( cell.v[1] - cell.v[2] ) * t;
            Dt = cell.v[3] + ( cell.v[0] - cell.v[3] ) * t;
        }
        else if (edge==8) {
            t  = cell.v[0] / ( cell.v[0] - cell.v[4] + epsilon );
            At = 0;
            Bt = cell.v[3] + ( cell.v[7] - cell.v[3] ) * t;
            Ct = cell.v[2] + ( cell.v[6] - cell.v[2] ) * t;
            Dt = cell.v[1] + ( cell.v[5] - cell.v[1] ) * t;
        }
        else if (edge==9) {
            t  = cell.v[1] / ( cell.v[1] - cell.v[5] + epsilon );
            At = 0;
            Bt = cell.v[0] + ( cell.v[4] - cell.v[0] ) * t;
            Ct = cell.v[3] + ( cell.v[7] - cell.v[3] ) * t;
            Dt = cell.v[2] + ( cell.v[6] - cell.v[2] ) * t;
        }
        else if (edge==10) {
            t  = cell.v[2] / ( cell.v[2] - cell.v[6] + epsilon );
            At = 0;
            Bt = cell.v[1] + ( cell.v[5] - cell.v[1] ) * t;
            Ct = cell.v[0] + ( cell.v[4] - cell.v[0] ) * t;
            Dt = cell.v[3] + ( cell.v[7] - cell.v[3] ) * t;
        }
        else if (edge==11) {
            t  = cell.v[3] / ( cell.v[3] - cell.v[7] + epsilon );
            At = 0;
            Bt = cell.v[2] + ( cell.v[6] - cell.v[2] ) * t;
            Ct = cell.v[1] + ( cell.v[5] - cell.v[1] ) * t;
            Dt = cell.v[0] + ( cell.v[4] - cell.v[0] ) * t;
        }
        else {
            std::printf("Invalid edge %i.\n", edge);
        }
    }
    else {
        std::printf("Invalid ambiguous case %i.\n", case_id);
    }
    if (At >= 0) { test += 1; }
    if (Bt >= 0) { test += 2; }
    if (Ct >= 0) { test += 4; }
    if (Dt >= 0) { test += 8; }
    if (test==0) { return s>0; }
    else if (test==1) { return s>0; }
    else if (test==2) { return s>0; }
    else if (test==3) { return s>0; }
    else if (test==4) { return s>0; }
    else if (test==5) {
        if (At * Ct - Bt * Dt <  epsilon) { return s>0; }
    }
    else if (test==6) { return s>0; }
    else if (test==7) { return s<0; }
    else if (test==8) { return s>0; }
    else if (test==9) { return s>0; }
    else if (test==10) {
        if (At * Ct - Bt * Dt >= epsilon) { return s>0; }
    }
    else if (test==11) { return s<0; }
    else if (test==12) { return s>0; }
    else if (test==13) { return s<0; }
    else if (test==14) { return s<0; }
    else if (test==15) { return s<0; }
    else { return s<0; }
    return 0;
}

