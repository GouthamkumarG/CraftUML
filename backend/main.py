import sys
import os
import asyncio
import uuid
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, validator

try:
    from diagram_generator.generator import EnhancedDiagramGenerator, DiagramConfig, DiagramGenerationError
except ImportError as e:
    print(f"Import error: {e}")
    raise

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Config:
    MAX_TEXT_LENGTH = 5000
    ALLOWED_DIAGRAM_TYPES = ["usecase", "sequence", "class", "auto"]
    MAX_CONCURRENT = 3

app = FastAPI(
    title="UML Diagram Generator API",
    description="Generate UML diagrams from natural language",
    version="2.0.0"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ensure backend static dir is used
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

generator = EnhancedDiagramGenerator()
semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT)

class DiagramRequest(BaseModel):
    text: str = Field(..., min_length=5, max_length=Config.MAX_TEXT_LENGTH)
    filename: str = Field(..., min_length=1, max_length=50)
    diagram_type: Optional[str] = Field("auto")

    @validator('diagram_type')
    def validate_type(cls, v):
        if v not in Config.ALLOWED_DIAGRAM_TYPES:
            raise ValueError(f'Must be one of {Config.ALLOWED_DIAGRAM_TYPES}')
        return v

    @validator('filename')
    def validate_filename(cls, v):
        import re
        return re.sub(r'[^\w\-_.]', '_', v)

class DiagramResponse(BaseModel):
    status: str
    request_id: str
    image_url: Optional[str] = None
    plantuml_url: Optional[str] = None
    diagram_type: Optional[str] = None
    error: Optional[str] = None
    generation_time: Optional[float] = None
    timestamp: str

def detect_diagram_type(text: str) -> str:
    text_lower = text.lower()
    
    if '->' in text_lower or 'sends' in text_lower or 'calls' in text_lower:
        return 'sequence'
    elif 'class' in text_lower or 'extends' in text_lower or 'implements' in text_lower:
        return 'class'
    else:
        return 'usecase'

@app.get("/")
async def root():
    return {
        "message": "UML Diagram Generator API",
        "version": "2.0.0",
        "supported_types": Config.ALLOWED_DIAGRAM_TYPES,
        "status": "operational"
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_generations": Config.MAX_CONCURRENT - semaphore._value
    }

@app.post("/generate-diagram", response_model=DiagramResponse)
async def create_diagram(request: DiagramRequest):
    request_id = str(uuid.uuid4())
    start_time = time.time()
    
    async with semaphore:
        try:
            logger.info(f"[{request_id[:8]}] Generating {request.filename}")
            
            diagram_type = request.diagram_type
            if diagram_type == "auto":
                diagram_type = detect_diagram_type(request.text)
                logger.info(f"Auto-detected: {diagram_type}")
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_filename = f"{request.filename}_{timestamp}"
            output_path = static_dir / safe_filename
            
            diagram_path = await asyncio.get_event_loop().run_in_executor(
                None,
                generator.generate_diagram_from_text,
                request.text,
                str(output_path),
                diagram_type
            )
            
            if Path(diagram_path).exists():
                image_filename = Path(diagram_path).name
                return DiagramResponse(
                    status="success",
                    request_id=request_id,
                    image_url=f"/static/{image_filename}",
                    plantuml_url=f"/plantuml/{Path(diagram_path).stem}",
                    diagram_type=diagram_type,
                    generation_time=time.time() - start_time,
                    timestamp=datetime.now().isoformat()
                )
            else:
                raise DiagramGenerationError("Failed to create diagram")
                
        except DiagramGenerationError as e:
            logger.error(f"[{request_id[:8]}] Generation error: {e}")
            return DiagramResponse(
                status="failed",
                request_id=request_id,
                error=str(e),
                generation_time=time.time() - start_time,
                timestamp=datetime.now().isoformat()
            )
        except Exception as e:
            logger.error(f"[{request_id[:8]}] Unexpected error: {e}")
            return DiagramResponse(
                status="error",
                request_id=request_id,
                error=f"Internal error: {str(e)}",
                generation_time=time.time() - start_time,
                timestamp=datetime.now().isoformat()
            )

@app.get("/image/{filename}")
async def get_image(filename: str):
    if not filename.endswith('.png'):
        filename += '.png'
    
    image_file = static_dir / filename
    if not image_file.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(image_file, media_type="image/png")

@app.get("/examples")
def get_examples():
    return {
        "usecase": [
            "Customer wishes to Withdraw Cash",
            "Admin wants to Manage Users",
            "Customer wishes to Withdraw Cash extending into Print Statement"
        ],
        "sequence": [
            "User -> System: Login Request\nSystem -> Database: Validate",
            "Customer -> OrderSystem: Place Order\nOrderSystem -> Payment: Process"
        ],
        "class": [
            "User class has name and email attributes",
            "Customer extends User class",
            "Order class has items and calculateTotal() method"
        ]
    }

@app.get("/plantuml/{filename}")
async def get_plantuml(filename: str):
    plantuml_file = static_dir / f"{filename}.txt"
    if not plantuml_file.exists():
        raise HTTPException(status_code=404, detail="PlantUML file not found")
    
    with open(plantuml_file, 'r', encoding='utf-8') as f:
        return {"filename": filename, "plantuml_code": f.read()}

@app.get("/download/plantuml/{filename}")
async def download_plantuml(filename: str):
    plantuml_file = static_dir / f"{filename}.txt"
    if not plantuml_file.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(plantuml_file, media_type="text/plain", filename=f"{filename}.puml")

@app.get("/download/image/{filename}")
async def download_image(filename: str):
    image_file = static_dir / f"{filename}.png"
    if not image_file.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(image_file, media_type="image/png", filename=f"{filename}.png")

@app.get("/files")
async def list_files():
    files = []
    if static_dir.exists():
        for file_path in static_dir.glob("*.png"):
            stat = file_path.stat()
            files.append({
                "filename": file_path.stem,
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "image_url": f"/static/{file_path.name}",
                "plantuml_url": f"/plantuml/{file_path.stem}"
            })
    
    files.sort(key=lambda x: x["created"], reverse=True)
    return {"total": len(files), "files": files[:20]}

@app.post("/validate")
async def validate_text(request: DiagramRequest):
    try:
        if not request.text.strip():
            raise ValueError("Text is empty")
        
        detected_type = detect_diagram_type(request.text)
        return {
            "status": "valid",
            "detected_type": detected_type,
            "text_length": len(request.text)
        }
    except Exception as e:
        return {
            "status": "invalid",
            "error": str(e),
            "max_length": Config.MAX_TEXT_LENGTH
        }

@app.get("/debug/files")
async def debug_files():
    files = []
    if static_dir.exists():
        for file_path in static_dir.iterdir():
            files.append({
                "name": file_path.name,
                "size": file_path.stat().st_size,
                "full_path": str(file_path.absolute())
            })
    return {
        "static_dir": str(static_dir.absolute()),
        "files": files,
        "cwd": os.getcwd()
    }

@app.get("/debug/plantuml-test")
async def test_plantuml():
    test_code = """@startuml
actor Customer
usecase "Test Case" as UC1
Customer --> UC1
@enduml"""
    
    try:
        import requests
        
        # test with direct POST first
        try:
            url = "http://www.plantuml.com/plantuml/png"
            response = requests.post(url, data=test_code, timeout=10)
            
            is_png = response.content.startswith(b'\x89PNG')
            
            return {
                "test": "PlantUML connectivity",
                "post_status": response.status_code,
                "content_length": len(response.content),
                "is_png": is_png,
                "suggestion": "Server is working" if is_png else "Server returned non-PNG content"
            }
        except Exception as post_error:
            # Fixed: Access _plantuml_encode from the generator instance
            encoded = generator._plantuml_encode(test_code)
            url = f"http://www.plantuml.com/plantuml/png/{encoded}"
            response = requests.get(url, timeout=10)
            
            return {
                "test": "PlantUML connectivity",
                "post_error": str(post_error),
                "encoded_url_status": response.status_code,
                "content_length": len(response.content),
                "is_png": response.content.startswith(b'\x89PNG'),
                "suggestion": "Check internet connection"
            }
    except Exception as e:
        return {
            "test": "PlantUML connectivity",
            "error": str(e),
            "suggestion": "Check internet connection or firewall settings"
        }

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting UML Diagram Generator...")
    logger.info("API docs: http://localhost:8000/docs")

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")