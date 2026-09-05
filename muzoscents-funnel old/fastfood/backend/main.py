from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# CORS – allow your Netlify frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://your-netlify-site.netlify.app",  # replace with your actual URL
        "http://localhost:3000",  # for local testing
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")  # use service key for admin
supabase: Client = create_client(supabase_url, supabase_key)

# ---------- Pydantic models ----------
class ProductBase(BaseModel):
    name: str
    description: Optional[str] = None
    price: int
    stock: int = 0
    tag: str
    emoji: str = "🍽️"
    image: Optional[str] = None
    tagColor: str = "primary"

class ProductCreate(ProductBase):
    pass

class ProductUpdate(ProductBase):
    pass

class Product(ProductBase):
    id: int

class CategoryBase(BaseModel):
    name: str

class Category(CategoryBase):
    id: int

class OrderItem(BaseModel):
    name: str
    qty: int
    price: int

class OrderCreate(BaseModel):
    payment_reference: str
    customer_name: str
    customer_phone: str
    total: int
    status: Optional[str] = "pending"
    delivery_method: Optional[str] = "pickup"
    delivery_address: Optional[str] = None
    preferred_time: Optional[str] = None
    order_notes: Optional[str] = None
    items: List[OrderItem]

class OrderStatusUpdate(BaseModel):
    status: str

# ---------- Endpoints ----------

# Products
@app.get("/api/products", response_model=List[Product])
async def get_products():
    res = supabase.table("products").select("*").order("name").execute()
    return res.data

@app.post("/api/products", response_model=Product)
async def create_product(product: ProductCreate):
    res = supabase.table("products").insert(product.dict()).execute()
    if not res.data:
        raise HTTPException(400, "Failed to create product")
    return res.data[0]

@app.put("/api/products/{product_id}")
async def update_product(product_id: int, product: ProductUpdate):
    res = supabase.table("products").update(product.dict()).eq("id", product_id).execute()
    if not res.data:
        raise HTTPException(404, "Product not found")
    return res.data[0]

@app.delete("/api/products/{product_id}")
async def delete_product(product_id: int):
    res = supabase.table("products").delete().eq("id", product_id).execute()
    if not res.data:
        raise HTTPException(404, "Product not found")
    return {"message": "deleted"}

# Categories
@app.get("/api/categories", response_model=List[Category])
async def get_categories():
    res = supabase.table("categories").select("*").order("name").execute()
    return res.data

@app.post("/api/categories", response_model=Category)
async def create_category(category: CategoryBase):
    res = supabase.table("categories").insert(category.dict()).execute()
    if not res.data:
        raise HTTPException(400, "Category already exists or invalid")
    return res.data[0]

@app.put("/api/categories/{category_id}")
async def update_category(category_id: int, category: CategoryBase):
    res = supabase.table("categories").update(category.dict()).eq("id", category_id).execute()
    if not res.data:
        raise HTTPException(404, "Category not found")
    return res.data[0]

@app.delete("/api/categories/{category_id}")
async def delete_category(category_id: int):
    res = supabase.table("categories").delete().eq("id", category_id).execute()
    if not res.data:
        raise HTTPException(404, "Category not found")
    return {"message": "deleted"}

# Orders
@app.get("/api/orders", response_model=List[Dict])
async def get_orders():
    res = supabase.table("orders").select("*").order("created_at", desc=True).execute()
    # add itemCount
    for o in res.data:
        o["itemCount"] = len(o.get("items", []))
    return res.data

@app.get("/api/orders/{order_id}")
async def get_order(order_id: int):
    res = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not res.data:
        raise HTTPException(404, "Order not found")
    return res.data[0]

@app.post("/api/orders")
async def create_order(order: OrderCreate):
    data = order.dict()
    # convert items to JSONB (it will be stored as JSON)
    res = supabase.table("orders").insert(data).execute()
    if not res.data:
        raise HTTPException(400, "Failed to create order")
    return res.data[0]

@app.patch("/api/orders/{order_id}/status")
async def update_order_status(order_id: int, status_update: OrderStatusUpdate):
    res = supabase.table("orders").update({"status": status_update.status}).eq("id", order_id).execute()
    if not res.data:
        raise HTTPException(404, "Order not found")
    return res.data[0]

# Stats
@app.get("/api/stats")
async def get_stats():
    # total products
    products_res = supabase.table("products").select("id", count="exact").execute()
    total_products = products_res.count

    # total categories
    cats_res = supabase.table("categories").select("id", count="exact").execute()
    total_categories = cats_res.count

    # total orders
    orders_res = supabase.table("orders").select("id", count="exact").execute()
    total_orders = orders_res.count

    # total revenue (sum of total of all orders)
    rev_res = supabase.table("orders").select("total").execute()
    total_revenue = sum(o["total"] for o in rev_res.data)

    return {
        "totalProducts": total_products,
        "totalCategories": total_categories,
        "totalOrders": total_orders,
        "totalRevenue": total_revenue
    }

# Health check
@app.get("/health")
async def health():
    return {"status": "ok"}
