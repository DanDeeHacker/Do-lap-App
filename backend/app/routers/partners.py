"""Partner referrals. Unlike the employer view, showing the referred
runner's name here is correct — the partner is the one who referred them,
so identity is already known to both sides (matches the original
prototype's privacy model)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from .. import models
from ..db import get_db
from ..deps import require_role
from ..serializers import to_dict, to_dicts

router = APIRouter(prefix="/api/partners", tags=["partners"])


@router.get("/{pid}/referrals")
def referrals(pid: str, user: models.User = Depends(require_role("partner")), db: DBSession = Depends(get_db)):
    if user.partner_id != pid:
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto partnerovi")
    rows = db.query(models.Referral).filter(models.Referral.partner_id == pid).all()
    out = []
    for ref in rows:
        r = db.query(models.Runner).filter(models.Runner.id == ref.runner_id).first()
        item = to_dict(ref)
        item["runner"] = to_dict(r)
        out.append(item)
    return out


@router.get("/{pid}/directory")
def directory(pid: str, user: models.User = Depends(require_role("partner")), db: DBSession = Depends(get_db)):
    """Physio/clinic directory for the "days" tab (proposing gait-analysis
    days at a partner venue) — professional names/specialties, not health
    data, so this is fine to expose to any authenticated partner."""
    if user.partner_id != pid:
        raise HTTPException(status_code=403, detail="Nemáte přístup k tomuto partnerovi")
    return {
        "physios": to_dicts(db.query(models.Physio).all()),
        "clinics": to_dicts(db.query(models.Clinic).all()),
    }
