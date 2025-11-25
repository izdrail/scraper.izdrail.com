import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.endpoints import scrapper


app = FastAPI(
    title="Scrapper API",
    description="This is a collection of endpoints that allows user to scrape social media",
    version="0.0.6",
    terms_of_service="https://izdrail.com/terms/",

    contact={
        "name": "Stefan",
        "url": "https://izdrail.com/",
        "email": "stefan@izdrail.com",
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    }
)

# Add CORS middleware - must be before mounting static files
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Create static directory if it doesn't exist
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Endpoints - include router after CORS and static files
app.include_router(scrapper.router)


@app.get("/")
async def root():
    return {"data": "You can try the latest API endpoint here -> /docs or use the UI at /ui"}


@app.get("/ui")
async def get_ui():
    """Serve the meme scraper UI from static files"""
    ui_file = static_dir / "index.html"

    if not ui_file.exists():
        return JSONResponse(
            status_code=404,
            content={
                "error": "UI file not found",
                "message": "Please create static/index.html file. See the documentation for the HTML template."
            }
        )

    return FileResponse(ui_file)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003, reload=True)