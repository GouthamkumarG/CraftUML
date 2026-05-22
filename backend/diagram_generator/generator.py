import os
import requests
import base64
import zlib
from pathlib import Path
from typing import Optional

from .config import (
    DiagramConfig, DiagramType, DiagramGenerationError,
    logger, clean_text, STOP_WORDS, CLASS_BLACKLIST, RELATIONSHIP_PATTERNS
)
from .parsers import (
    detect_diagram_type, parse_relationships, extract_entities_nlp,
    generate_use_case_diagram, generate_sequence_diagram, generate_class_diagram
)

class DiagramGenerator:
    """Main diagram generator class that orchestrates the generation process."""
    
    def __init__(self, config: DiagramConfig = None):
        self.config = config or DiagramConfig()
        self.stop_words = STOP_WORDS
        self.class_blacklist = CLASS_BLACKLIST
        self.relationship_patterns = RELATIONSHIP_PATTERNS
        
        # Make methods available as instance methods
        self.clean_text = clean_text
        self.extract_entities_nlp = extract_entities_nlp
        self.detect_diagram_type = detect_diagram_type
        self.parse_relationships = parse_relationships
        self.generate_use_case_diagram = generate_use_case_diagram
        self.generate_sequence_diagram = generate_sequence_diagram
        self.generate_class_diagram = generate_class_diagram

    def generate_diagram_from_text(self, text: str, output_path: str, diagram_type: str = None) -> str:
        """Main entry point for generating diagrams from text."""
        if not text or not text.strip():
            raise DiagramGenerationError("Input text is empty")
        
        if len(text) > self.config.max_line_length * 50:
            raise DiagramGenerationError("Input text is too long")
        
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        
        if not lines:
            raise DiagramGenerationError("No valid input lines found")
        
        if not diagram_type or diagram_type == "auto":
            diagram_type = detect_diagram_type(text)
            logger.info(f"Auto-detected diagram type: {diagram_type}")
        
        if diagram_type == "sequence":
            plantuml_code = generate_sequence_diagram(lines)
        elif diagram_type == "class":
            plantuml_code = generate_class_diagram(lines)
        else:
            plantuml_code = generate_use_case_diagram(lines)
        
        logger.info(f"Generated PlantUML code:\n{plantuml_code}")
        return self.generate_diagram_via_web(plantuml_code, output_path)

    def _plantuml_encode(self, text: str) -> str:
        """Encode PlantUML text to URL-safe format."""
        compressed = zlib.compress(text.encode('utf-8'))
        encoded = base64.b64encode(compressed).decode('ascii')
        # PlantUML specific encoding
        encoded = encoded.translate(str.maketrans('+/', '-_'))
        return encoded.rstrip('=')

    def generate_diagram_via_web(self, plantuml_code: str, output_path: str) -> str:
        """Generate diagram using PlantUML web service."""
        try:
            logger.info(f"Generating diagram with PlantUML code:\n{plantuml_code}")
            
            # Method 1: Direct POST with proper headers
            try:
                url = "http://www.plantuml.com/plantuml/png"
                headers = {
                    'Content-Type': 'text/plain; charset=utf-8',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                response = requests.post(
                    url, 
                    data=plantuml_code.encode('utf-8'), 
                    headers=headers, 
                    timeout=30,
                    allow_redirects=True
                )
                
                logger.info(f"POST response status: {response.status_code}")
                logger.info(f"Response headers: {dict(response.headers)}")
                logger.info(f"Content type: {response.headers.get('content-type', 'unknown')}")
                logger.info(f"Content length: {len(response.content)}")
                logger.info(f"Content starts with PNG: {response.content.startswith(b'\\x89PNG')}")
                
                if response.status_code == 200 and response.content.startswith(b'\x89PNG'):
                    logger.info("Successfully generated diagram via POST")
                    return self._save_diagram(plantuml_code, output_path, response.content)
                
            except Exception as e:
                logger.error(f"POST method failed: {e}")
            
            # Method 2: Simple GET with basic syntax
            try:
                simple_plantuml = f"@startuml\nactor Alice\nactor Bob\nAlice -> Bob\n@enduml"
                
                url = "http://www.plantuml.com/plantuml/png"
                response = requests.post(url, data=simple_plantuml, timeout=30)
                
                if response.status_code == 200 and response.content.startswith(b'\x89PNG'):
                    logger.info("Simple test worked - using original code")
                    response2 = requests.post(url, data=plantuml_code, timeout=30)
                    if response2.status_code == 200 and response2.content.startswith(b'\x89PNG'):
                        return self._save_diagram(plantuml_code, output_path, response2.content)
                
            except Exception as e:
                logger.error(f"Simple test failed: {e}")
            
            # Method 3:  alternative PlantUML server
            try:
                url = "https://kroki.io/plantuml/png"
                headers = {'Content-Type': 'text/plain'}
                
                response = requests.post(url, data=plantuml_code, headers=headers, timeout=30)
                
                if response.status_code == 200 and response.content.startswith(b'\x89PNG'):
                    logger.info("Successfully generated diagram via Kroki")
                    return self._save_diagram(plantuml_code, output_path, response.content)
                    
            except Exception as e:
                logger.error(f"Kroki method failed: {e}")
            
            logger.info("All methods failed - using local fallback")
            return self._generate_local_fallback(plantuml_code, output_path)
                
        except Exception as e:
            logger.error(f"Complete failure: {e}")
            return self._generate_local_fallback(plantuml_code, output_path)
    
    def _save_diagram(self, plantuml_code: str, output_path: str, image_content: bytes) -> str:
        """Save the generated diagram and PlantUML source."""
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
        
        with open(f"{output_path}.txt", "w", encoding="utf-8") as f:
            f.write(plantuml_code)
        
        diagram_path = f"{output_path}.png"
        with open(diagram_path, 'wb') as f:
            f.write(image_content)
        
        logger.info(f"Diagram saved successfully: {diagram_path} ({len(image_content)} bytes)")
        return diagram_path
    
    def _generate_local_fallback(self, plantuml_code: str, output_path: str) -> str:
        """Generate fallback diagram when web service fails."""
        try:
            try:
                from PIL import Image, ImageDraw, ImageFont
                return self._generate_pil_fallback(plantuml_code, output_path)
            except ImportError:
                return self._generate_simple_fallback(plantuml_code, output_path)
                
        except Exception as e:
            logger.error(f"Fallback generation failed: {e}")
            raise DiagramGenerationError(f"All diagram generation methods failed: {e}")
    
    def _generate_pil_fallback(self, plantuml_code: str, output_path: str) -> str:
        """Generate fallback diagram using PIL."""
        from PIL import Image, ImageDraw, ImageFont
        
        img = Image.new('RGB', (1000, 700), color='white')
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("arial.ttf", 14)
            title_font = ImageFont.truetype("arial.ttf", 18)
        except:
            font = ImageFont.load_default()
            title_font = ImageFont.load_default()
        
        draw.text((20, 20), "UML Diagram (Fallback Mode)", fill='navy', font=title_font)
        draw.text((20, 50), "PlantUML server unavailable - showing parsed content", fill='red', font=font)
        
        draw.rectangle([15, 80, 985, 680], outline='black', width=2)
        
        lines = plantuml_code.split('\n')
        y = 100
        for line in lines:
            line = line.strip()
            if line and not line.startswith('@') and not line.startswith('!'):
                display_line = line
                color = 'black'
                
                if 'actor' in line:
                    color = 'blue'
                    display_line = "Actor: " + line.replace('actor', '').strip()
                elif 'usecase' in line:
                    color = 'green'
                    display_line = "Use Case: " + line.replace('usecase', '').strip()
                elif '-->' in line:
                    color = 'purple'
                    display_line = "Relationship: " + line
                elif '..>' in line:
                    color = 'orange'
                    display_line = "Special: " + line
                
                draw.text((30, y), display_line, fill=color, font=font)
                y += 25
                if y > 650:
                    break
        
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
        diagram_path = f"{output_path}.png"
        img.save(diagram_path, 'PNG')
        
        with open(f"{output_path}.txt", "w", encoding="utf-8") as f:
            f.write(plantuml_code)
        
        logger.info(f"PIL fallback diagram generated: {diagram_path}")
        return diagram_path
    
    def _generate_simple_fallback(self, plantuml_code: str, output_path: str) -> str:
        """Generate simple fallback when PIL is not available."""
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
        
        with open(f"{output_path}.txt", "w", encoding="utf-8") as f:
            f.write(plantuml_code)
        
        try:
            from PIL import Image, ImageDraw
            img = Image.new('RGB', (800, 600), color='white')
            draw = ImageDraw.Draw(img)
            draw.text((50, 50), "PlantUML Diagram Generation Failed", fill='red')
            draw.text((50, 100), "Please check the .txt file for PlantUML source", fill='black')
            
            diagram_path = f"{output_path}.png"
            img.save(diagram_path)
            return diagram_path
        except:
            return f"{output_path}.txt"

def generate_usecase_diagram_from_text(text: str, output_path: str) -> str:
    """Standalone function for backward compatibility."""
    generator = DiagramGenerator()
    return generator.generate_diagram_from_text(text, output_path)

# ================== Exports for backward compatibility ==================
# This allows main.py to import without changes
EnhancedDiagramGenerator = DiagramGenerator  # Alias for backward compatibility

from .config import DiagramConfig, DiagramGenerationError

__all__ = [
    'DiagramGenerator',
    'EnhancedDiagramGenerator',  # For backward compatibility
    'generate_usecase_diagram_from_text',
    'DiagramConfig',
    'DiagramGenerationError'
]