from enum import StrEnum


class AccountType(StrEnum):
    CA_NHAN = "CA_NHAN"
    DICH_VU_CI = "DICH_VU_CI"


class AccountStatus(StrEnum):
    HOAT_DONG = "HOAT_DONG"
    TAM_KHOA = "TAM_KHOA"


class Platform(StrEnum):
    GITHUB = "GITHUB"
    CUC_BO = "CUC_BO"


class RepoStatus(StrEnum):
    DANG_HOAT_DONG = "DANG_HOAT_DONG"
    NGUNG_THEO_DOI = "NGUNG_THEO_DOI"


class RoleName(StrEnum):
    LAP_TRINH_VIEN = "LAP_TRINH_VIEN"
    NGUOI_REVIEW = "NGUOI_REVIEW"
    QUAN_LY_DU_AN = "QUAN_LY_DU_AN"
    NGUOI_DANH_GIA = "NGUOI_DANH_GIA"


class PRStatus(StrEnum):
    DANG_MO = "DANG_MO"
    DA_DONG = "DA_DONG"
    DA_HOP_NHAT = "DA_HOP_NHAT"


class WebhookProcessStatus(StrEnum):
    TIEP_NHAN = "TIEP_NHAN"
    DA_TAO_LUOT = "DA_TAO_LUOT"
    BO_QUA = "BO_QUA"
    LOI = "LOI"


class InputSource(StrEnum):
    GITHUB_PR = "GITHUB_PR"
    CLI_CUC_BO = "CLI_CUC_BO"
    IDE_PLUGIN = "IDE_PLUGIN"


class ChangeType(StrEnum):
    THEM_MOI = "THEM_MOI"
    CHINH_SUA = "CHINH_SUA"
    XOA = "XOA"
    DOI_TEN = "DOI_TEN"


class PatchStatus(StrEnum):
    CO_PATCH = "CO_PATCH"
    THIEU_PATCH = "THIEU_PATCH"
    NHI_PHAN = "NHI_PHAN"
    NGOAI_PHAM_VI = "NGOAI_PHAM_VI"


class ToolSource(StrEnum):
    RUFF = "RUFF"
    BANDIT = "BANDIT"
    AST_CUSTOM = "AST_CUSTOM"
    CONVENTION = "CONVENTION"


class SourceType(StrEnum):
    RUFF = "RUFF"
    BANDIT = "BANDIT"
    AST_CUSTOM = "AST_CUSTOM"
    CONVENTION = "CONVENTION"
    LLM = "LLM"


class Category(StrEnum):
    CHUC_NANG = "CHUC_NANG"
    BAO_MAT = "BAO_MAT"
    HIEU_NANG = "HIEU_NANG"
    BAO_TRI = "BAO_TRI"
    QUY_UOC = "QUY_UOC"


class Severity(StrEnum):
    CAO = "CAO"
    TRUNG_BINH = "TRUNG_BINH"
    THAP = "THAP"


class ExecutionMode(StrEnum):
    A_STATIC = "A_STATIC"
    B_LLM = "B_LLM"
    C_NOI_KET_QUA = "C_NOI_KET_QUA"
    D_KET_HOP = "D_KET_HOP"


class ContextPolicy(StrEnum):
    DIFF_ONLY = "DIFF_ONLY"
    DIFF_AST = "DIFF_AST"
    DIFF_AST_INTENT = "DIFF_AST_INTENT"
    KHONG_AP_DUNG = "KHONG_AP_DUNG"


class RunStatus(StrEnum):
    CHO_XU_LY = "CHO_XU_LY"
    DANG_CHAY = "DANG_CHAY"
    HOAN_THANH = "HOAN_THANH"
    MOT_PHAN = "MOT_PHAN"
    THAT_BAI = "THAT_BAI"


class CallPurpose(StrEnum):
    REVIEW = "REVIEW"
    XAC_MINH = "XAC_MINH"
    THU_LAI = "THU_LAI"


class CallStatus(StrEnum):
    THANH_CONG = "THANH_CONG"
    QUA_HAN = "QUA_HAN"
    LOI_DICH_VU = "LOI_DICH_VU"
    SAI_SCHEMA = "SAI_SCHEMA"


class UsageSource(StrEnum):
    THUC_TE = "THUC_TE"
    UOC_TINH = "UOC_TINH"
    KHONG_CO = "KHONG_CO"


class AssessmentStatus(StrEnum):
    CO_VAN_DE = "CO_VAN_DE"
    CAN_XAC_MINH = "CAN_XAC_MINH"
    KHONG_QUAN_SAT_THAY = "KHONG_QUAN_SAT_THAY"
    CHUA_DU_THONG_TIN = "CHUA_DU_THONG_TIN"
    KHONG_AP_DUNG = "KHONG_AP_DUNG"


class DiffSide(StrEnum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class FindingKind(StrEnum):
    LOI_TIEM_AN = "LOI_TIEM_AN"
    GOI_Y_TOI_UU = "GOI_Y_TOI_UU"


class EvidenceStatus(StrEnum):
    CO_CAN_CU = "CO_CAN_CU"
    CAN_XAC_MINH = "CAN_XAC_MINH"


class FixVerificationStatus(StrEnum):
    CHUA_KIEM_CHUNG = "CHUA_KIEM_CHUNG"
    DA_KIEM_CHUNG = "DA_KIEM_CHUNG"
    KHONG_AP_DUNG = "KHONG_AP_DUNG"


class FilterStatus(StrEnum):
    GIU_LAI = "GIU_LAI"
    LOAI_SAI_DONG = "LOAI_SAI_DONG"
    LOAI_TRUNG = "LOAI_TRUNG"
    LOAI_THIEU_CAN_CU = "LOAI_THIEU_CAN_CU"
    LOI_CU = "LOI_CU"


class FeedbackLabel(StrEnum):
    DUNG = "DUNG"
    SAI = "SAI"
    CAN_XAC_MINH = "CAN_XAC_MINH"


class CommentScope(StrEnum):
    TONG_HOP_PR = "TONG_HOP_PR"
    NHAN_XET_DONG = "NHAN_XET_DONG"


class PublishStatus(StrEnum):
    CHO_DANG = "CHO_DANG"
    DA_DANG = "DA_DANG"
    BO_QUA_LOI_THOI = "BO_QUA_LOI_THOI"
    LOI_DANG = "LOI_DANG"
    CAN_DOI_SOAT = "CAN_DOI_SOAT"


class ArtifactType(StrEnum):
    RAW_SNAPSHOT = "RAW_SNAPSHOT"
    RAW_PROMPT = "RAW_PROMPT"
    RAW_LLM_OUTPUT = "RAW_LLM_OUTPUT"
    REPORT_JSON = "REPORT_JSON"
    REPORT_MD = "REPORT_MD"
    REPORT_SARIF = "REPORT_SARIF"


class PurgeStatus(StrEnum):
    CON_LUU = "CON_LUU"
    DA_XOA = "DA_XOA"
    LOI_XOA = "LOI_XOA"
