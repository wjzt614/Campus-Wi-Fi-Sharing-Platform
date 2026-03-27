"""
校园WIFI共享系统 - 基于博弈论激励机制
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel
from datetime import datetime, timedelta
import random, os, asyncio, json as _json

app = FastAPI(title="校园WIFI共享系统")
_sse_subscribers: dict[int, list] = {}

SQLALCHEMY_DATABASE_URL = "sqlite:///./campus_wifi.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── 模型 ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    email = Column(String, unique=True, index=True)
    reputation_score = Column(Float, default=100.0)
    reputation_level = Column(String, default="silver")
    virtual_currency = Column(Float, default=100.0)
    total_bandwidth_shared = Column(Float, default=0.0)
    total_bandwidth_used = Column(Float, default=0.0)
    # 滑动窗口：30天内分享/消费（JSON字符串存每日记录）
    recent_shared_30d = Column(Float, default=0.0)
    recent_used_30d   = Column(Float, default=0.0)
    joined_at = Column(DateTime, default=datetime.utcnow)   # 注册时间，用于新用户豁免
    online_hours = Column(Float, default=0.0)
    violation_count = Column(Integer, default=0)
    is_frozen = Column(Boolean, default=False)
    frozen_until = Column(DateTime, nullable=True)
    coalition_id = Column(Integer, nullable=True)
    guarantor_id = Column(Integer, nullable=True)
    guarantor_earned = Column(Float, default=0.0)   # 担保人累计佣金收入
    trust_quota = Column(Float, default=50.0)
    is_online = Column(Boolean, default=False)
    last_active = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

class BandwidthShare(Base):
    __tablename__ = "bandwidth_shares"
    id = Column(Integer, primary_key=True, index=True)
    sharer_id = Column(Integer, index=True)
    bandwidth_amount = Column(Float)
    price_per_mb = Column(Float)
    is_available = Column(Boolean, default=True)
    is_peak_hour = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)

class BandwidthTransaction(Base):
    __tablename__ = "bandwidth_transactions"
    id = Column(Integer, primary_key=True, index=True)
    sharer_id = Column(Integer, index=True)
    user_id = Column(Integer, index=True)
    bandwidth_amount = Column(Float)
    price_paid = Column(Float)
    transaction_type = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Coalition(Base):
    __tablename__ = "coalitions"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    total_shared = Column(Float, default=0.0)
    total_used   = Column(Float, default=0.0)
    # 联盟内互消费节省的折扣总额（用于Shapley分配）
    total_saved  = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ── 迁移 ─────────────────────────────────────────────────────────────────────

def run_migrations():
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(users)"))
        existing = {row[1] for row in result}
        for col, sql in {
            "reputation_level":   "ALTER TABLE users ADD COLUMN reputation_level TEXT DEFAULT 'silver'",
            "online_hours":       "ALTER TABLE users ADD COLUMN online_hours FLOAT DEFAULT 0.0",
            "violation_count":    "ALTER TABLE users ADD COLUMN violation_count INTEGER DEFAULT 0",
            "is_frozen":          "ALTER TABLE users ADD COLUMN is_frozen BOOLEAN DEFAULT 0",
            "frozen_until":       "ALTER TABLE users ADD COLUMN frozen_until DATETIME",
            "coalition_id":       "ALTER TABLE users ADD COLUMN coalition_id INTEGER",
            "guarantor_id":       "ALTER TABLE users ADD COLUMN guarantor_id INTEGER",
            "guarantor_earned":   "ALTER TABLE users ADD COLUMN guarantor_earned FLOAT DEFAULT 0.0",
            "trust_quota":        "ALTER TABLE users ADD COLUMN trust_quota FLOAT DEFAULT 50.0",
            "virtual_currency":   "ALTER TABLE users ADD COLUMN virtual_currency FLOAT DEFAULT 100.0",
            "recent_shared_30d":  "ALTER TABLE users ADD COLUMN recent_shared_30d FLOAT DEFAULT 0.0",
            "recent_used_30d":    "ALTER TABLE users ADD COLUMN recent_used_30d FLOAT DEFAULT 0.0",
            "joined_at":          "ALTER TABLE users ADD COLUMN joined_at DATETIME",
        }.items():
            if col not in existing:
                conn.execute(text(sql)); conn.commit()

        result = conn.execute(text("PRAGMA table_info(bandwidth_shares)"))
        existing_bs = {row[1] for row in result}
        if "is_peak_hour" not in existing_bs:
            conn.execute(text("ALTER TABLE bandwidth_shares ADD COLUMN is_peak_hour BOOLEAN DEFAULT 0"))
            conn.commit()

        result = conn.execute(text("PRAGMA table_info(coalitions)"))
        existing_c = {row[1] for row in result}
        if "total_saved" not in existing_c:
            conn.execute(text("ALTER TABLE coalitions ADD COLUMN total_saved FLOAT DEFAULT 0.0"))
            conn.commit()

run_migrations()

# ── Pydantic ──────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str; password: str; email: str

class UserLogin(BaseModel):
    username: str; password: str

class BandwidthShareCreate(BaseModel):
    bandwidth_amount: float; user_id: int; is_peak_hour: bool = False

class BandwidthRequest(BaseModel):
    bandwidth_amount: float; user_id: int

class CoalitionCreate(BaseModel):
    name: str; user_id: int

class JoinCoalition(BaseModel):
    user_id: int; coalition_id: int

class GuaranteeRequest(BaseModel):
    guarantor_id: int; new_user_id: int

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ── 博弈论引擎 ────────────────────────────────────────────────────────────────

REPUTATION_LEVELS = [("diamond", 90), ("gold", 70), ("silver", 50), ("bronze", 0)]

def get_reputation_level(score: float) -> str:
    for level, threshold in REPUTATION_LEVELS:
        if score >= threshold: return level
    return "bronze"

def reputation_discount(level: str) -> float:
    return {"diamond": 0.30, "gold": 0.15, "silver": 0.0, "bronze": -1.0}[level]

def is_peak_hour() -> bool:
    return 8 <= datetime.utcnow().hour <= 22

def is_new_user_exempt(user: User) -> bool:
    """新用户注册7天内豁免搭便车惩罚"""
    if not user.joined_at: return False
    return (datetime.utcnow() - user.joined_at).days < 7

def get_dynamic_base_price(db: Session) -> float:
    """动态基础价格：带宽池紧张时涨价，充裕时降价（建议5）"""
    shares = db.query(BandwidthShare).filter(BandwidthShare.is_available == True).all()
    total = sum(s.bandwidth_amount for s in shares)
    # 以500MB为基准，低于则涨价，高于则降价，幅度±10%
    if total <= 0: return 0.12
    ratio = total / 500.0
    if ratio < 0.8:   return round(0.1 * 1.1, 4)   # 涨10%
    elif ratio > 1.2: return round(0.1 * 0.9, 4)   # 降10%
    return 0.1

def get_contribution_ratio_30d(user: User) -> float:
    """30天滑动窗口贡献比（建议3）"""
    s = user.recent_shared_30d or 0
    u = user.recent_used_30d or 0
    total = s + u
    if total == 0:
        # 新用户给中性值
        return 0.5
    return s / total

def rejection_probability(ratio: float) -> float:
    """线性拒绝概率：贡献比0%→100%拒绝，9%→10%拒绝，≥10%→0（建议7）"""
    if ratio >= 0.1: return 0.0
    return (0.1 - ratio) * 10.0  # 0~1.0

class GameTheoryEngine:
    @staticmethod
    def discount_factor(reputation_score: float, recent_share_rate: float = 0.5) -> float:
        """δ = 0.5 + 0.005×min(信誉,100) + 0.1×近7天分享率（建议6）"""
        base = 0.5 + 0.005 * min(reputation_score, 100)
        activity_bonus = 0.1 * min(recent_share_rate, 1.0)
        return min(0.99, base + activity_bonus)

    @staticmethod
    def share_rep_multiplier(reputation_score: float, recent_share_rate: float = 0.5) -> float:
        delta = GameTheoryEngine.discount_factor(reputation_score, recent_share_rate)
        return 1.0 + (delta - 0.5) / 0.49 * 1.0  # 1.0x ~ 2.0x

    @staticmethod
    def shapley_value(members: list, total_value: float) -> dict:
        """按联盟内互消费贡献比分配Shapley值（建议1）"""
        n = len(members)
        if n == 0: return {}
        total_shared = sum(m['shared'] for m in members)
        return {
            m['id']: total_value * (m['shared'] / total_shared if total_shared > 0 else 1/n)
            for m in members
        }

    @staticmethod
    def detect_mutual_wash(user_id: int, sharer_id: int, db: Session) -> bool:
        """互刷检测：1小时内双向交易超过10MB（建议4）"""
        cutoff = datetime.utcnow() - timedelta(hours=1)
        # A消费B
        ab = db.query(BandwidthTransaction).filter(
            BandwidthTransaction.user_id == user_id,
            BandwidthTransaction.sharer_id == sharer_id,
            BandwidthTransaction.transaction_type == 'use',
            BandwidthTransaction.created_at >= cutoff
        ).all()
        # B消费A
        ba = db.query(BandwidthTransaction).filter(
            BandwidthTransaction.user_id == sharer_id,
            BandwidthTransaction.sharer_id == user_id,
            BandwidthTransaction.transaction_type == 'use',
            BandwidthTransaction.created_at >= cutoff
        ).all()
        ab_vol = sum(t.bandwidth_amount for t in ab)
        ba_vol = sum(t.bandwidth_amount for t in ba)
        return ab_vol > 10 and ba_vol > 10

# ── 带宽管理器 ────────────────────────────────────────────────────────────────

class BandwidthManager:
    @staticmethod
    def allocate(user_id: int, amount: float, db: Session):
        user = db.query(User).filter(User.id == user_id).first()
        if not user: return None, "用户不存在"

        # 冻结检查
        if user.is_frozen:
            if user.frozen_until and datetime.utcnow() < user.frozen_until:
                return None, f"账户已冻结至 {user.frozen_until.strftime('%Y-%m-%d %H:%M')}"
            user.is_frozen = False

        level = get_reputation_level(user.reputation_score)
        if level == "bronze":
            return None, "⚫ 青铜级用户禁止获取共享带宽，请先分享带宽提升信誉"

        # 30天滑动窗口贡献比（建议3）
        ratio = get_contribution_ratio_30d(user)
        exempt = is_new_user_exempt(user)

        # 线性拒绝概率（建议7）
        # 保护期内：免拒绝和冻结，但价格惩罚照常
        if not exempt:
            reject_prob = rejection_probability(ratio)
            if reject_prob > 0 and random.random() < reject_prob:
                if ratio < 0.1:
                    user.violation_count = (user.violation_count or 0) + 1
                    if user.violation_count >= 5:
                        user.is_frozen = True
                        user.frozen_until = datetime.utcnow() + timedelta(days=3)
                        db.commit()
                        return None, f"⚠️ 长期搭便车（已记录{user.violation_count}次），账户已冻结3天"
                    db.commit()
                return None, f"⚠️ 搭便车拦截（贡献比{ratio*100:.1f}%，拒绝概率{reject_prob*100:.0f}%），请先分享带宽"

        # 惩罚系数：保护期内照常涨价，只是不会被拒绝/冻结
        if ratio < 0.1:   penalty = 2.0   # +100%
        elif ratio < 0.2: penalty = 1.5   # +50%
        else:             penalty = 1.0

        # 联盟优先匹配（建议1）
        coalition_shares, from_coalition = [], False
        if user.coalition_id:
            member_ids = [m.id for m in db.query(User).filter(
                User.coalition_id == user.coalition_id, User.id != user_id).all()]
            if member_ids:
                coalition_shares = db.query(BandwidthShare).filter(
                    BandwidthShare.is_available == True,
                    BandwidthShare.bandwidth_amount >= amount,
                    BandwidthShare.sharer_id.in_(member_ids)
                ).order_by(BandwidthShare.price_per_mb).all()

        global_shares = db.query(BandwidthShare).filter(
            BandwidthShare.is_available == True,
            BandwidthShare.bandwidth_amount >= amount,
            BandwidthShare.sharer_id != user_id
        ).order_by(BandwidthShare.price_per_mb).all()

        shares = coalition_shares if coalition_shares else global_shares
        from_coalition = bool(coalition_shares)
        if not shares: return None, "暂无其他用户的可用带宽，请等待其他人分享"

        share = shares[0]

        # 互刷检测（建议4）
        wash_detected = GameTheoryEngine.detect_mutual_wash(user_id, share.sharer_id, db)

        # 动态基础价格（建议5）
        base_price = get_dynamic_base_price(db)
        discount = reputation_discount(level)
        coalition_discount = 0.08 if from_coalition else 0.0

        # 建议9：排行榜前10%用户额外5%折扣
        total_users = db.query(User).count()
        top_threshold = max(1, int(total_users * 0.1))
        top_users = db.query(User).order_by(User.reputation_score.desc()).limit(top_threshold).all()
        top_bonus = 0.05 if any(u.id == user_id for u in top_users) else 0.0

        actual_price = base_price * (1 - discount - coalition_discount - top_bonus) * penalty
        actual_price = max(actual_price, 0.001)
        total_cost = amount * actual_price

        if user.virtual_currency < total_cost:
            return None, f"校园币不足，需要 {total_cost:.2f}，当前 {user.virtual_currency:.2f}"

        # 执行交易
        user.virtual_currency -= total_cost
        user.total_bandwidth_used += amount
        user.recent_used_30d = (user.recent_used_30d or 0) + amount
        # 消费扣信誉
        user.reputation_score = max(0, user.reputation_score - amount * 0.05)
        user.reputation_level = get_reputation_level(user.reputation_score)

        share.bandwidth_amount -= amount
        if share.bandwidth_amount <= 0: share.is_available = False

        sharer = db.query(User).filter(User.id == share.sharer_id).first()
        sharer_rep_gain = 0.0
        if sharer:
            # 互刷时不给额外信誉奖励（建议4）
            if not wash_detected:
                recent_rate = (sharer.recent_shared_30d or 0) / max(
                    (sharer.recent_shared_30d or 0) + (sharer.recent_used_30d or 0), 1)
                rep_mult = GameTheoryEngine.share_rep_multiplier(sharer.reputation_score, recent_rate)
                sharer_rep_gain = amount * 0.1 * rep_mult
                sharer.reputation_score = min(200, sharer.reputation_score + sharer_rep_gain)
                sharer.reputation_level = get_reputation_level(sharer.reputation_score)
            sharer.virtual_currency += total_cost
            sharer.recent_shared_30d = (sharer.recent_shared_30d or 0)  # 分享时已记录

            # 担保人佣金 1%（建议2）
            if sharer.guarantor_id:
                guarantor = db.query(User).filter(User.id == sharer.guarantor_id).first()
                if guarantor:
                    commission = total_cost * 0.01
                    guarantor.virtual_currency += commission
                    guarantor.guarantor_earned = (guarantor.guarantor_earned or 0) + commission
                    _notify_sse(guarantor.id, guarantor.virtual_currency)

            # 联盟节省统计（建议1）
            if from_coalition and sharer.coalition_id:
                saved = amount * base_price * 0.08
                sc = db.query(Coalition).filter(Coalition.id == sharer.coalition_id).first()
                if sc:
                    sc.total_used = (sc.total_used or 0) + amount
                    sc.total_saved = (sc.total_saved or 0) + saved

        db.add(BandwidthTransaction(
            sharer_id=share.sharer_id, user_id=user_id,
            bandwidth_amount=amount, price_paid=total_cost, transaction_type='use'
        ))
        db.commit()

        _notify_sse(sharer.id if sharer else 0, sharer.virtual_currency if sharer else 0)
        _broadcast_pool_update()

        return {
            "total_cost": total_cost, "actual_price": actual_price,
            "penalty": penalty, "ratio": ratio, "level": level,
            "discount": discount, "coalition_discount": coalition_discount,
            "top_bonus": top_bonus,
            "from_coalition": from_coalition, "wash_detected": wash_detected,
            "base_price": base_price,
            "rep_cost": amount * 0.05,
            "sharer_rep_gain": sharer_rep_gain,
        }, None

def _notify_sse(user_id: int, currency: float):
    if user_id in _sse_subscribers:
        payload = _json.dumps({"virtual_currency": round(currency, 2)})
        for q in list(_sse_subscribers[user_id]):
            try: q.put_nowait(payload)
            except: pass

def _broadcast_pool_update():
    """交易发生后广播带宽池变化，通知所有在线用户刷新"""
    payload = _json.dumps({"pool_updated": True})
    for uid, queues in list(_sse_subscribers.items()):
        for q in list(queues):
            try: q.put_nowait(payload)
            except: pass

# ── API 路由 ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/register")
async def register(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(400, "用户名已存在")
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(400, "邮箱已被注册")
    try:
        db_user = User(username=user.username, password=user.password,
                       email=user.email, joined_at=datetime.utcnow())
        db.add(db_user); db.commit(); db.refresh(db_user)
        return {"message": "注册成功", "user_id": db_user.id}
    except Exception:
        db.rollback()
        raise HTTPException(400, "注册失败，用户名或邮箱已存在")

@app.post("/api/login")
async def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(
        User.username == user.username, User.password == user.password).first()
    if not db_user: raise HTTPException(401, "用户名或密码错误")
    db_user.is_online = True; db_user.last_active = datetime.utcnow(); db.commit()
    return {
        "user_id": db_user.id, "username": db_user.username,
        "reputation_score": db_user.reputation_score,
        "reputation_level": db_user.reputation_level or get_reputation_level(db_user.reputation_score),
        "virtual_currency": db_user.virtual_currency,
    }

@app.post("/api/share-bandwidth")
async def share_bandwidth(share: BandwidthShareCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == share.user_id).first()
    if not user: raise HTTPException(404, "用户不存在")

    peak = share.is_peak_hour or is_peak_hour()
    recent_rate = (user.recent_shared_30d or 0) / max(
        (user.recent_shared_30d or 0) + (user.recent_used_30d or 0), 1)
    delta_mult = GameTheoryEngine.share_rep_multiplier(user.reputation_score, recent_rate)
    base_rep = share.bandwidth_amount * (0.2 if peak else 0.1)
    rep_reward = base_rep * delta_mult

    db.add(BandwidthShare(
        sharer_id=share.user_id, bandwidth_amount=share.bandwidth_amount,
        price_per_mb=0.1, is_peak_hour=peak,
        expires_at=datetime.utcnow() + timedelta(hours=24)
    ))
    db.add(BandwidthTransaction(
        sharer_id=share.user_id, user_id=share.user_id,
        bandwidth_amount=share.bandwidth_amount, price_paid=0, transaction_type='share'
    ))
    user.total_bandwidth_shared += share.bandwidth_amount
    user.recent_shared_30d = (user.recent_shared_30d or 0) + share.bandwidth_amount
    user.reputation_score = min(200, user.reputation_score + rep_reward)
    user.reputation_level = get_reputation_level(user.reputation_score)

    if user.coalition_id:
        c = db.query(Coalition).filter(Coalition.id == user.coalition_id).first()
        if c: c.total_shared += share.bandwidth_amount

    db.commit()
    _broadcast_pool_update()
    return {
        "message": "分享成功，等待他人消费后获得校园币",
        "reputation_reward": rep_reward, "delta_multiplier": delta_mult,
        "is_peak": peak, "new_balance": user.virtual_currency,
        "new_reputation": user.reputation_score, "new_level": user.reputation_level
    }

@app.post("/api/request-bandwidth")
async def request_bandwidth(req: BandwidthRequest, db: Session = Depends(get_db)):
    # 建议8：先预告费用和信誉变化
    result, err = BandwidthManager.allocate(req.user_id, req.bandwidth_amount, db)
    if err:
        code = 403 if any(k in err for k in ["搭便车", "青铜", "冻结"]) else 400
        raise HTTPException(code, err)
    return {
        "message": "带宽分配成功", "bandwidth_amount": req.bandwidth_amount,
        "total_cost": result["total_cost"], "actual_price": result["actual_price"],
        "base_price": result["base_price"],
        "penalty": result["penalty"], "contribution_ratio": result["ratio"],
        "reputation_level": result["level"], "discount": result["discount"],
        "coalition_discount": result["coalition_discount"],
        "top_bonus": result["top_bonus"],
        "from_coalition": result["from_coalition"],
        "wash_detected": result["wash_detected"],
        "rep_cost": result["rep_cost"],
    }

@app.get("/api/cost-preview")
async def cost_preview(user_id: int, amount: float, db: Session = Depends(get_db)):
    """建议8：消费前预告价格和信誉变化"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "用户不存在")
    level = get_reputation_level(user.reputation_score)
    ratio = get_contribution_ratio_30d(user)
    exempt = is_new_user_exempt(user)
    # 保护期内价格惩罚照常，只豁免拒绝/冻结
    if ratio < 0.1:   penalty = 2.0
    elif ratio < 0.2: penalty = 1.5
    else:             penalty = 1.0
    base_price = get_dynamic_base_price(db)
    discount = reputation_discount(level)
    actual_price = base_price * (1 - discount) * penalty
    actual_price = max(actual_price, 0.001)
    total_cost = amount * actual_price
    rep_cost = amount * 0.05
    reject_prob = rejection_probability(ratio) if not exempt else 0.0
    return {
        "estimated_cost": round(total_cost, 3),
        "actual_price_per_mb": round(actual_price, 4),
        "base_price": base_price,
        "reputation_discount": discount,
        "penalty_multiplier": penalty,
        "rep_cost": rep_cost,
        "current_reputation": user.reputation_score,
        "after_reputation": max(0, user.reputation_score - rep_cost),
        "current_currency": user.virtual_currency,
        "after_currency": max(0, user.virtual_currency - total_cost),
        "reject_probability": round(reject_prob, 2),
        "contribution_ratio": round(ratio, 3),
        "new_user_exempt": exempt,
    }

@app.post("/api/coalition/create")
async def create_coalition(req: CoalitionCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user: raise HTTPException(404, "用户不存在")
    c = Coalition(name=req.name); db.add(c); db.flush()
    user.coalition_id = c.id; db.commit()
    return {"message": "联盟创建成功", "coalition_id": c.id, "name": c.name}

@app.post("/api/coalition/join")
async def join_coalition(req: JoinCoalition, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == req.user_id).first()
    c = db.query(Coalition).filter(Coalition.id == req.coalition_id).first()
    if not user or not c: raise HTTPException(404, "用户或联盟不存在")
    user.coalition_id = req.coalition_id; db.commit()
    return {"message": f"成功加入联盟 {c.name}"}

@app.get("/api/coalition/{coalition_id}")
async def get_coalition(coalition_id: int, db: Session = Depends(get_db)):
    c = db.query(Coalition).filter(Coalition.id == coalition_id).first()
    if not c: raise HTTPException(404, "联盟不存在")
    members = db.query(User).filter(User.coalition_id == coalition_id).all()
    # Shapley值基于联盟内互消费节省的折扣总额（建议1）
    member_data = [{"id": m.id, "shared": m.total_bandwidth_shared} for m in members]
    shapley = GameTheoryEngine.shapley_value(member_data, c.total_saved or 0)
    return {
        "id": c.id, "name": c.name,
        "total_shared": c.total_shared, "total_used": c.total_used,
        "total_saved": c.total_saved,   # 联盟内互消费节省的校园币总额
        "member_count": len(members),
        "members": [
            {"id": m.id, "username": m.username,
             "reputation_level": m.reputation_level or get_reputation_level(m.reputation_score),
             "shared": m.total_bandwidth_shared,
             "shapley_value": shapley.get(m.id, 0)}
            for m in members
        ]
    }

@app.post("/api/trust/guarantee")
async def guarantee_user(req: GuaranteeRequest, db: Session = Depends(get_db)):
    guarantor = db.query(User).filter(User.id == req.guarantor_id).first()
    new_user  = db.query(User).filter(User.id == req.new_user_id).first()
    if not guarantor or not new_user: raise HTTPException(404, "用户不存在")
    if get_reputation_level(guarantor.reputation_score) not in ("diamond", "gold"):
        raise HTTPException(403, "只有黄金及以上用户才能担保新用户")
    if new_user.guarantor_id:
        raise HTTPException(400, "该用户已有担保人")
    new_user.guarantor_id = req.guarantor_id
    new_user.trust_quota = 150.0
    new_user.virtual_currency += 50
    db.commit()
    return {"message": f"担保成功，{new_user.username} 信任额度已提升，你将获得其消费额1%佣金",
            "new_quota": new_user.trust_quota}

@app.get("/api/user-stats/{user_id}")
async def get_user_stats(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "用户不存在")
    total = user.total_bandwidth_shared + user.total_bandwidth_used
    ratio_all = user.total_bandwidth_shared / total if total > 0 else 0.5
    ratio_30d = get_contribution_ratio_30d(user)
    level = user.reputation_level or get_reputation_level(user.reputation_score)
    recent_rate = (user.recent_shared_30d or 0) / max(
        (user.recent_shared_30d or 0) + (user.recent_used_30d or 0), 1)
    delta = GameTheoryEngine.discount_factor(user.reputation_score, recent_rate)
    exempt = is_new_user_exempt(user)
    reject_prob = rejection_probability(ratio_30d) if not exempt else 0.0
    return {
        "username": user.username,
        "reputation_score": user.reputation_score,
        "reputation_level": level,
        "virtual_currency": user.virtual_currency,
        "total_bandwidth_shared": user.total_bandwidth_shared,
        "total_bandwidth_used": user.total_bandwidth_used,
        "contribution_ratio": ratio_30d,        # 30天窗口
        "contribution_ratio_all": ratio_all,    # 历史总计
        "recent_shared_30d": user.recent_shared_30d or 0,
        "recent_used_30d": user.recent_used_30d or 0,
        "violation_count": user.violation_count or 0,
        "is_frozen": user.is_frozen,
        "coalition_id": user.coalition_id,
        "guarantor_id": user.guarantor_id,
        "guarantor_earned": user.guarantor_earned or 0,
        "trust_quota": user.trust_quota,
        "discount_factor": delta,
        "new_user_exempt": exempt,
        "reject_probability": round(reject_prob, 2),
    }

@app.get("/api/available-bandwidth")
async def get_available_bandwidth(user_id: int = None, db: Session = Depends(get_db)):
    all_shares = db.query(BandwidthShare).filter(BandwidthShare.is_available == True).all()
    total = sum(s.bandwidth_amount for s in all_shares)
    avg_price = sum(s.price_per_mb for s in all_shares) / len(all_shares) if all_shares else 0
    my_contributed, max_requestable = 0.0, total
    if user_id:
        my_shares = [s for s in all_shares if s.sharer_id == user_id]
        my_contributed = sum(s.bandwidth_amount for s in my_shares)
        others = [s for s in all_shares if s.sharer_id != user_id]
        max_requestable = sum(s.bandwidth_amount for s in others)
    dynamic_price = get_dynamic_base_price(db)
    return {
        "total_available_bandwidth": total,
        "average_price_per_mb": avg_price,
        "dynamic_base_price": dynamic_price,
        "share_count": len(all_shares),
        "my_contributed": my_contributed,
        "max_requestable": max_requestable,
    }

@app.get("/api/leaderboard")
async def get_leaderboard(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.reputation_score.desc()).limit(10).all()
    # 建议9：前10%额外5%折扣标记
    total_users = db.query(User).count()
    top_threshold = max(1, int(total_users * 0.1))
    return {"leaderboard": [
        {"rank": i+1, "username": u.username,
         "reputation_score": u.reputation_score,
         "reputation_level": u.reputation_level or get_reputation_level(u.reputation_score),
         "virtual_currency": u.virtual_currency,
         "total_bandwidth_shared": u.total_bandwidth_shared,
         "top_bonus": i < top_threshold}   # 前10%享额外5%折扣
        for i, u in enumerate(users)
    ]}

@app.get("/api/coalitions")
async def get_all_coalitions(db: Session = Depends(get_db)):
    coalitions = db.query(Coalition).all()
    result = []
    for c in coalitions:
        count = db.query(User).filter(User.coalition_id == c.id).count()
        result.append({"id": c.id, "name": c.name, "total_shared": c.total_shared,
                       "total_saved": c.total_saved or 0, "member_count": count})
    return {"coalitions": result}

@app.get("/api/currency-stream/{user_id}")
async def currency_stream(user_id: int):
    queue: asyncio.Queue = asyncio.Queue()
    _sse_subscribers.setdefault(user_id, []).append(queue)
    async def gen():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=25)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            subs = _sse_subscribers.get(user_id, [])
            if queue in subs: subs.remove(queue)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
