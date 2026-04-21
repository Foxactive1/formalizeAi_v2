from config import REQUIRED_SECTIONS

class Validator:
    @staticmethod
    def validate(sdd: str) -> dict:
        if not sdd:
            return {"valid": False, "missing": REQUIRED_SECTIONS}
        # FIX: comparação case-insensitive para tolerar variações de capitalização do modelo
        sdd_lower = sdd.lower()
        missing = [
            sec for sec in REQUIRED_SECTIONS
            if sec not in sdd and sec.lower() not in sdd_lower
        ]
        return {"valid": len(missing) == 0, "missing": missing}