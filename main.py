from fastapi import FastAPI, Response, status 
import os
import time 

from routers.Ai import take_doc_route
from routers.auth import auth_route
# from routers.likes import likes_route
# from routers.posts import posts_route
from routers.users import users_routes



from fastapi.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager
from redis.asyncio import Redis


from core.Exceptions.exception_handlers import global_exception_handler, unexpected_exception_handler
from core.Exceptions.exceptions import AppException


from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from core.rate_limiters.limiter_file import limiter



from utils.logging.config import setup_logging
setup_logging() 




@asynccontextmanager
async def lifespan(app: FastAPI):

    print("Starting application")
    app.state.redis = Redis(
        host="localhost",
        port=6379,
        decode_responses=True
    )

    yield

    print("Closing application")
    await app.state.redis.close()


app = FastAPI(
    title="Social Network Aggregator API",
    lifespan=lifespan
)

#shows ms in swagger
@app.middleware("http")
async def add_process_time_header(request, call_next):
    start_time = time.perf_counter()
    response: Response = await call_next(request)
    process_time_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Process-Time-Ms"] = f"{process_time_ms:.2f} ms"
    return response


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


app.add_exception_handler(
    AppException,
    global_exception_handler  
)

app.add_exception_handler(
    Exception, 
    unexpected_exception_handler 
)



origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",

    "http://localhost:3000",
    "http://127.0.0.1:3000",

    "http://localhost:8080",
    "http://127.0.0.1:8080",

    "http://localhost:4200",
    "http://127.0.0.1:4200",

    "http://10.0.2.2:8000",  #

    "https://www.yourdomain.com",
    "https://yourdomain.com",
    "https://staging.yourdomain.com",
]
from utils.config import settings
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = settings.api_key
os.environ["LANGCHAIN_PROJECT"] = "fastapi-ai-blog"




app.add_middleware(
    CORSMiddleware, 
    allow_origins=origins, 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"], 
)

# app.include_router(router=posts_route.router)
app.include_router(router=users_routes.router)
app.include_router(router=auth_route.router)
app.include_router(router=take_doc_route.router)
# app.include_router(router=likes_route.router)
# app.include_router(router=ai_route_copy.router)



from fastapi import status
@app.get("/", status_code=status.HTTP_200_OK)
def root():
    return {"message": "Hello World"}


from dotenv import load_dotenv
load_dotenv()  