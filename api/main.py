from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json

from api.database import get_db, init_db, User, Customer, PartnershipCode, FinancialTransaction
from api.auth import (
    verify_password, 
    get_password_hash, 
    create_access_token, 
    get_current_user,
    require_permission,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from api.models import (
    Token, UserResponse, CustomerCreate, CustomerResponse,
    PartnershipCodeCreate, PartnershipCodeResponse, PartnershipStats,
    FinancialResponse, FinancialPeriod, FinancialDetail,
    UserCreate, UserUpdate
)

app = FastAPI(title="Admin Dashboard API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    try:
        init_db()
        print("Database initialized successfully")
    except Exception as e:
        print(f"Error initializing database: {e}")


@app.get("/")
def root():
    return {"message": "Admin Dashboard API", "status": "running"}

@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    try:
        # Test database connection
        user_count = db.query(User).count()
        return {
            "status": "healthy",
            "database": "connected",
            "user_count": user_count
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "error",
            "error": str(e)
        }


# Authentication endpoints
@app.post("/api/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.email == form_data.username).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if not verify_password(form_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )
        
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.email}, expires_delta=access_token_expires
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": UserResponse.model_validate(user)
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during login"
        )


@app.get("/api/me", response_model=UserResponse)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


# Customer endpoints
@app.post("/api/customers", response_model=CustomerResponse)
def create_customer(
    customer: CustomerCreate,
    current_user: User = Depends(require_permission("can_manage_customers")),
    db: Session = Depends(get_db)
):
    # Validate partnership code if provided
    if customer.partnership_code:
        partnership_code = db.query(PartnershipCode).filter(
            PartnershipCode.code == customer.partnership_code,
            PartnershipCode.is_active == True
        ).first()
        if not partnership_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or inactive partnership code"
            )
    
    # Calculate total price
    total_price = sum(customer.prices)
    
    db_customer = Customer(
        full_name=customer.full_name,
        phone=customer.phone,
        email=customer.email,
        class_level=customer.class_level,
        camps=json.dumps(customer.camps),
        prices=json.dumps(customer.prices),
        partnership_code=customer.partnership_code,
        previous_yks_rank=customer.previous_yks_rank,
        city=customer.city,
        is_paid=True if total_price > 0 else False
    )
    
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    
    # Create financial transaction
    if total_price > 0:
        transaction = FinancialTransaction(
            customer_id=db_customer.id,
            amount=total_price
        )
        db.add(transaction)
        db.commit()
    
    # Parse JSON fields for response
    customer_response = CustomerResponse.model_validate(db_customer)
    customer_response.camps = json.loads(db_customer.camps) if db_customer.camps else []
    customer_response.prices = json.loads(db_customer.prices) if db_customer.prices else []
    
    return customer_response


@app.get("/api/customers", response_model=list[CustomerResponse])
def get_customers(
    current_user: User = Depends(require_permission("can_manage_customers")),
    db: Session = Depends(get_db),
    include_deleted: bool = False
):
    query = db.query(Customer)
    if not include_deleted:
        query = query.filter(Customer.is_deleted == False)
    
    customers = query.order_by(Customer.created_at.desc()).all()
    
    result = []
    for customer in customers:
        customer_response = CustomerResponse.model_validate(customer)
        customer_response.camps = json.loads(customer.camps) if customer.camps else []
        customer_response.prices = json.loads(customer.prices) if customer.prices else []
        result.append(customer_response)
    
    return result


@app.delete("/api/customers/{customer_id}")
def delete_customer(
    customer_id: int,
    current_user: User = Depends(require_permission("can_manage_customers")),
    db: Session = Depends(get_db)
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )
    
    customer.is_deleted = True
    customer.deleted_at = datetime.utcnow()
    
    # Mark financial transactions as deleted and subtract from total
    transactions = db.query(FinancialTransaction).filter(
        FinancialTransaction.customer_id == customer_id,
        FinancialTransaction.is_deleted == False
    ).all()
    
    for transaction in transactions:
        transaction.is_deleted = True
    
    db.commit()
    
    return {"message": "Customer marked as deleted (payment not received)"}


# Financial endpoints
@app.get("/api/financials", response_model=FinancialResponse)
def get_financials(
    current_user: User = Depends(require_permission("can_view_financials")),
    db: Session = Depends(get_db)
):
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Get all active transactions
    all_transactions = db.query(FinancialTransaction).filter(
        FinancialTransaction.is_deleted == False
    ).all()
    
    # Calculate totals
    daily_total = sum(t.amount for t in all_transactions if t.transaction_date >= today_start)
    weekly_total = sum(t.amount for t in all_transactions if t.transaction_date >= week_start)
    monthly_total = sum(t.amount for t in all_transactions if t.transaction_date >= month_start)
    yearly_total = sum(t.amount for t in all_transactions if t.transaction_date >= year_start)
    total = sum(t.amount for t in all_transactions)
    
    # Get details with customer info
    details = []
    for transaction in all_transactions:
        customer = db.query(Customer).filter(Customer.id == transaction.customer_id).first()
        if customer and not customer.is_deleted:
            details.append(FinancialDetail(
                customer_id=customer.id,
                customer_name=customer.full_name,
                amount=transaction.amount,
                transaction_date=transaction.transaction_date
            ))
    
    return FinancialResponse(
        period=FinancialPeriod(
            daily=daily_total,
            weekly=weekly_total,
            monthly=monthly_total,
            yearly=yearly_total
        ),
        details=details,
        total=total
    )


# Partnership code endpoints
@app.post("/api/partnership-codes", response_model=PartnershipCodeResponse)
def create_partnership_code(
    code_data: PartnershipCodeCreate,
    current_user: User = Depends(require_permission("can_manage_partnership_codes")),
    db: Session = Depends(get_db)
):
    existing = db.query(PartnershipCode).filter(PartnershipCode.code == code_data.code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Partnership code already exists"
        )
    
    partnership_code = PartnershipCode(code=code_data.code)
    db.add(partnership_code)
    db.commit()
    db.refresh(partnership_code)
    
    return PartnershipCodeResponse.model_validate(partnership_code)


@app.get("/api/partnership-codes", response_model=list[PartnershipCodeResponse])
def get_partnership_codes(
    current_user: User = Depends(require_permission("can_manage_partnership_codes")),
    db: Session = Depends(get_db)
):
    codes = db.query(PartnershipCode).order_by(PartnershipCode.created_at.desc()).all()
    return [PartnershipCodeResponse.model_validate(code) for code in codes]


@app.delete("/api/partnership-codes/{code_id}")
def delete_partnership_code(
    code_id: int,
    current_user: User = Depends(require_permission("can_manage_partnership_codes")),
    db: Session = Depends(get_db)
):
    code = db.query(PartnershipCode).filter(PartnershipCode.id == code_id).first()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partnership code not found"
        )
    
    code.is_active = False
    db.commit()
    
    return {"message": "Partnership code deactivated"}


# Partnership stats endpoint
@app.get("/api/partnership-stats", response_model=list[PartnershipStats])
def get_partnership_stats(
    current_user: User = Depends(require_permission("can_view_partnership_stats")),
    db: Session = Depends(get_db)
):
    codes = db.query(PartnershipCode).all()
    stats = []
    
    for code in codes:
        customers = db.query(Customer).filter(
            Customer.partnership_code == code.code,
            Customer.is_deleted == False
        ).all()
        
        total_amount = 0
        for customer in customers:
            prices = json.loads(customer.prices) if customer.prices else []
            total_amount += sum(prices)
        
        stats.append(PartnershipStats(
            code=code.code,
            customer_count=len(customers),
            total_amount=total_amount
        ))
    
    return sorted(stats, key=lambda x: x.total_amount, reverse=True)


# User management endpoints
@app.post("/api/users", response_model=UserResponse)
def create_user(
    user_data: UserCreate,
    current_user: User = Depends(require_permission("can_manage_access")),
    db: Session = Depends(get_db)
):
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )
    
    user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        can_manage_customers=user_data.can_manage_customers,
        can_view_financials=user_data.can_view_financials,
        can_manage_partnership_codes=user_data.can_manage_partnership_codes,
        can_view_partnership_stats=user_data.can_view_partnership_stats,
        can_manage_access=user_data.can_manage_access
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return UserResponse.model_validate(user)


@app.get("/api/users", response_model=list[UserResponse])
def get_users(
    current_user: User = Depends(require_permission("can_manage_access")),
    db: Session = Depends(get_db)
):
    users = db.query(User).all()
    return [UserResponse.model_validate(user) for user in users]


@app.put("/api/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user: User = Depends(require_permission("can_manage_access")),
    db: Session = Depends(get_db)
):
    # Prevent modifying gokhan and emre
    protected_emails = ["gokhan@kampus.com", "emre@kampus.com"]
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if user.email in protected_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify protected user accounts"
        )
    
    # Update fields
    if user_data.can_manage_customers is not None:
        user.can_manage_customers = user_data.can_manage_customers
    if user_data.can_view_financials is not None:
        user.can_view_financials = user_data.can_view_financials
    if user_data.can_manage_partnership_codes is not None:
        user.can_manage_partnership_codes = user_data.can_manage_partnership_codes
    if user_data.can_view_partnership_stats is not None:
        user.can_view_partnership_stats = user_data.can_view_partnership_stats
    if user_data.can_manage_access is not None:
        user.can_manage_access = user_data.can_manage_access
    if user_data.is_active is not None:
        user.is_active = user_data.is_active
    
    db.commit()
    db.refresh(user)
    
    return UserResponse.model_validate(user)


@app.delete("/api/users/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(require_permission("can_manage_access")),
    db: Session = Depends(get_db)
):
    # Prevent deleting gokhan and emre
    protected_emails = ["gokhan@kampus.com", "emre@kampus.com"]
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if user.email in protected_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete protected user accounts"
        )
    
    # Deactivate instead of delete
    user.is_active = False
    db.commit()
    
    return {"message": "User deactivated"}

