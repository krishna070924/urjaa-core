import os
os.environ.setdefault("DATABASE_URL","postgresql://postgres:postgres@localhost:5432/urjaa")
from fastapi import HTTPException
from urjaa_core.services.admin.admin_management_service import AdminManagementService as A

class C:
    def __init__(self, name, bm): self.name=name; self.base_metal_id=bm

GOLD, SILVER_METAL = 27, 99

# colour belongs to the chosen metal -> allowed
A._validate_metal_colour_pairing(C("Yellow", GOLD), GOLD); print("Gold + Yellow            -> allowed  OK")

# colour belongs to another metal -> rejected
try:
    A._validate_metal_colour_pairing(C("Rose", GOLD), SILVER_METAL)
    print("Silver + Rose            -> ALLOWED  FAIL")
except HTTPException as e:
    print(f"Silver + Rose            -> rejected {e.status_code}  OK")

# unclassified colour (0019 left it NULL) -> allowed, so existing data keeps working
A._validate_metal_colour_pairing(C("Silver", None), GOLD); print("Gold + unclassified      -> allowed  OK")

# no metal chosen -> nothing to check
A._validate_metal_colour_pairing(C("Yellow", GOLD), None); print("no metal selected        -> allowed  OK")
print("ALL OK")
