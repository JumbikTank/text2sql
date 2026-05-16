COLUMN_DESCRIPTIONS = {
    "LOAN_NUM": "Column LOAN_NUM: Unique Identification Number of Loan",
    "DELQ_DAY_MBA_ID": "Column DELQ_DAY_MBA_ID: It's the Delinquent days as per MBA method",
    "ST_CNTY_ID": "Column ST_CNTY_ID: Code that indicates the FIPS County and State code",
    "LOAN_TYP_CD": "Column LOAN_TYP_CD: Code to indicate whether the loan is FHA, VA, conventional, etc",
    "INT_RNG_ID": "Column INT_RNG_ID: Code to indicate the low & high range of the interest",
    "CR_GRD_CD": "Column CR_GRD_CD: Code to indicate the credit grade of the borrower",
    "SVCS_TYP_CD": "Column SVCS_TYP_CD: Code to indicate the service type of the borrower",
    "LQDTN_TYP_CD": "Column LQDTN_TYP_CD: Code that indicates the type of liquidation",
}

TABLE_DEPENDENCIES = {
    "bdl.f_loan_me_t": [
        (
            COLUMN_DESCRIPTIONS["DELQ_DAY_MBA_ID"],
            "bdl.d_delq_mba_t",
            "column DELQ_DAY_MBA_ID",
        ),
        (COLUMN_DESCRIPTIONS["ST_CNTY_ID"], "bdl.d_st_cnty_t", "column ST_CNTY_ID"),
        (COLUMN_DESCRIPTIONS["LOAN_TYP_CD"], "bdl.d_loan_typ_t", "column LOAN_TYP_CD"),
        (COLUMN_DESCRIPTIONS["INT_RNG_ID"], "bdl.d_int_rate_t", "column INT_RNG_ID"),
        (COLUMN_DESCRIPTIONS["CR_GRD_CD"], "bdl.lkp_cr_grd_t", "column CR_GRD_CD"),
        (
            COLUMN_DESCRIPTIONS["SVCS_TYP_CD"],
            "bdl.lkp_svcs_typ_t",
            "column SVCS_TYP_CD",
        ),
        (
            COLUMN_DESCRIPTIONS["LQDTN_TYP_CD"],
            "bdl.lkp_lqdtn_typ_t",
            "column LQDTN_TYP_CD",
        ),
    ],
    "bdl.ivr_intacs_t": [
        (COLUMN_DESCRIPTIONS["LOAN_NUM"], "bdl.f_loan_me_t", "column LOAN_NUMBER")
    ],
    "bdl.email_intacs_t": [
        (COLUMN_DESCRIPTIONS["LOAN_NUM"], "bdl.f_loan_me_t", "column LOAN_NUMBER")
    ],
    "bdl.ltr_intacs_t": [
        (COLUMN_DESCRIPTIONS["LOAN_NUM"], "bdl.f_loan_me_t", "column LOAN_NUMBER")
    ],
    "bdl.web_intacs_t": [
        (COLUMN_DESCRIPTIONS["LOAN_NUM"], "bdl.f_loan_me_t", "column LOAN_NUMBER")
    ],
    "bdl.paymt_chnl_t": [
        (COLUMN_DESCRIPTIONS["LOAN_NUM"], "bdl.f_loan_me_t", "column LOAN_NUMBER")
    ],
    "bdl.cmplnts_data_t": [
        (COLUMN_DESCRIPTIONS["LOAN_NUM"], "bdl.f_loan_me_t", "column LOAN_NUMBER")
    ],
    "bdl.ivr_calls_t": [
        (COLUMN_DESCRIPTIONS["LOAN_NUM"], "bdl.f_loan_me_t", "column LOAN_NUMBER")
    ],
    "bdl.d_st_cnty_t": [
        (COLUMN_DESCRIPTIONS["LOAN_NUM"], "bdl.f_loan_me_t", "column LOAN_NUMBER")
    ],
}
