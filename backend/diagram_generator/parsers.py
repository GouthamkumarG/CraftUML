import re
from typing import List, Dict, Set, Tuple, Any
from .config import (
    logger, nlp, clean_text, sanitize_id,
    CLASS_BLACKLIST, RELATIONSHIP_PATTERNS
)

# ================== Entity Extraction ==================

def extract_entities_nlp(text: str) -> Dict[str, Any]:
    """Extract entities from text using NLP."""
    doc = nlp(text)
    entities = {
        'actors': set(),
        'classes': set(),
        'use_cases': set(),
        'methods': set(),
        'attributes': set(),
        'relationships': []
    }
    
    for ent in getattr(doc, 'ents', []):
        if getattr(ent, 'label_', '') in ("PERSON", "ORG"):
            clean_ent = clean_text(ent.text)
            if clean_ent:
                entities['actors'].add(clean_ent)
    
    for token in doc:
        token_text = getattr(token, 'text', str(token))
        token_pos = getattr(token, 'pos_', '')
        token_dep = getattr(token, 'dep_', '')
        token_lemma = getattr(token, 'lemma_', token_text.lower())
        
        if token_pos == "NOUN" and token_text.lower() not in CLASS_BLACKLIST:
            clean_noun = clean_text(token_text)
            if clean_noun:
                if token_dep in ("nsubj", "ROOT"):
                    entities['classes'].add(clean_noun)
                else:
                    entities['attributes'].add(clean_noun)
        
        elif token_pos == "VERB" and token_lemma not in {'be', 'have', 'do', 'is', 'are'}:
            if len(token_lemma) > 2:
                entities['methods'].add(f"+{token_lemma}() : void")
    
    return entities

def detect_diagram_type(text: str) -> str:
    """Detect the most appropriate diagram type from text."""
    text_lower = text.lower()
    
    scores = {'usecase': 0, 'sequence': 0, 'class': 0}
    
    usecase_keywords = ['actor', 'wishes to', 'wants to', 'use case', 'extends', 'includes', 'customer', 'user']
    scores['usecase'] = sum(3 if keyword in text_lower else 0 for keyword in usecase_keywords)
    
    sequence_keywords = ['->', 'sends', 'calls', 'responds', 'returns', 'message', 'request']
    scores['sequence'] = sum(4 if '->' in text_lower else 2 if keyword in text_lower else 0 for keyword in sequence_keywords)
    
    class_keywords = ['class', 'extends', 'implements', 'method', 'attribute', 'interface', 'inheritance']
    scores['class'] = sum(3 if keyword in text_lower else 0 for keyword in class_keywords)
    
    detected_type = max(scores, key=scores.get) if max(scores.values()) > 0 else 'usecase'
    logger.info(f"Diagram type detection - Scores: {scores}, Selected: {detected_type}")
    return detected_type

def parse_relationships(line: str) -> List[Tuple[str, str, str]]:
    """Parse relationships from a line of text."""
    relationships = []
    
    for rel_type, pattern in RELATIONSHIP_PATTERNS.items():
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            source = clean_text(match.group(1))
            target = clean_text(match.group(2))
            if source and target and source != target:
                relationships.append((source, target, rel_type))
    
    return relationships

# ================== Diagram Generators ==================

def generate_use_case_diagram(lines: List[str]) -> str:
    """Generate PlantUML code for a use case diagram."""
    actors = set()
    use_cases = set()
    relationships = []
    includes = []
    extends = []
    
    for line in lines:
        if not line.strip():
            continue
        
        line = line.strip()
        
        if "->" in line:
            parts = line.split("->", 1)
            if len(parts) == 2:
                actor = clean_text(parts[0])
                use_case = clean_text(parts[1])
                if actor and use_case:
                    actors.add(actor)
                    use_cases.add(use_case)
                    relationships.append((actor, use_case))
                continue
        
        parsed_rels = parse_relationships(line)
        for source, target, rel_type in parsed_rels:
            if rel_type == 'wishes':
                actors.add(source)
                use_cases.add(target)
                relationships.append((source, target))
            elif rel_type == 'includes':
                use_cases.update([source, target])
                includes.append((source, target))
            elif rel_type == 'extends':
                use_cases.update([source, target])
                extends.append((source, target))
        
        if line.lower().startswith("actor:"):
            actor = clean_text(line.split(":", 1)[1])
            if actor:
                actors.add(actor)
        elif line.lower().startswith("use case:"):
            use_case = clean_text(line.split(":", 1)[1])
            if use_case:
                use_cases.add(use_case)
        
        elif not parsed_rels:
            entities = extract_entities_nlp(line)
            actors.update(entities['actors'])
            use_cases.update(entities['use_cases'])
    
    return build_use_case_plantuml(actors, use_cases, relationships, includes, extends)

def generate_sequence_diagram(lines: List[str]) -> str:
    """Generate PlantUML code for a sequence diagram."""
    participants = set()
    interactions = []
    
    for line in lines:
        if not line.strip():
            continue
        
        match = re.search(r"(.+?)\s*->\s*(.+?)\s*:\s*(.+)", line.strip())
        if match:
            sender = clean_text(match.group(1))
            receiver = clean_text(match.group(2))
            message = match.group(3).strip()
            
            if sender and receiver:
                participants.update([sender, receiver])
                interactions.append(f"{sender} -> {receiver}: {message}")
            continue
        
        match = re.search(r"(.+?)\s*->\s*(.+)", line.strip())
        if match:
            sender = clean_text(match.group(1))
            receiver = clean_text(match.group(2))
            
            if sender and receiver:
                participants.update([sender, receiver])
                interactions.append(f"{sender} -> {receiver}: message")
            continue
        
        entities = extract_entities_nlp(line)
        if len(entities['actors']) >= 2:
            actors_list = list(entities['actors'])[:2]
            participants.update(actors_list)
            if entities['methods']:
                method = list(entities['methods'])[0].split('(')[0].replace('+', '')
                interactions.append(f"{actors_list[0]} -> {actors_list[1]}: {method}")
    
    return build_sequence_plantuml(participants, interactions)

def generate_class_diagram(lines: List[str]) -> str:
    """Generate PlantUML code for a class diagram."""
    classes = {}
    methods = {}
    relationships = []
    
    for line in lines:
        if not line.strip():
            continue
        
        entities = extract_entities_nlp(line)
        
        for class_name in entities['classes']:
            if class_name not in classes:
                classes[class_name] = set()
                methods[class_name] = set()
            
            classes[class_name].update(entities['attributes'])
            methods[class_name].update(entities['methods'])
        
        parsed_rels = parse_relationships(line)
        for source, target, rel_type in parsed_rels:
            if rel_type in ['extends', 'implements', 'uses']:
                relationships.append((source, target, rel_type))
                for cls in [source, target]:
                    if cls not in classes:
                        classes[cls] = set()
                        methods[cls] = set()
    
    return build_class_plantuml(classes, methods, relationships)

# ================== PlantUML Builders ==================

def build_use_case_plantuml(actors, use_cases, relationships, includes, extends) -> str:
    """Build PlantUML code for a use case diagram."""
    plantuml = "@startuml\n"
    
    actor_ids = {}
    usecase_ids = {}
    
    for actor in sorted(actors):
        actor_id = sanitize_id(actor)
        actor_ids[actor] = actor_id
        plantuml += f'actor "{actor}" as {actor_id}\n'
    
    plantuml += "\n"
    
    for use_case in sorted(use_cases):
        uc_id = sanitize_id(use_case)
        usecase_ids[use_case] = uc_id
        plantuml += f'usecase "{use_case}" as {uc_id}\n'
    
    plantuml += "\n"
    
    for actor, use_case in relationships:
        if actor in actor_ids and use_case in usecase_ids:
            plantuml += f"{actor_ids[actor]} --> {usecase_ids[use_case]}\n"
    
    for base, included in includes:
        if base in usecase_ids and included in usecase_ids:
            plantuml += f"{usecase_ids[base]} ..> {usecase_ids[included]} : <<include>>\n"
    
    for base, extension in extends:
        if base in usecase_ids and extension in usecase_ids:
            plantuml += f"{usecase_ids[extension]} ..> {usecase_ids[base]} : <<extend>>\n"
    
    plantuml += "@enduml"
    return plantuml

def build_sequence_plantuml(participants, interactions) -> str:
    """Build PlantUML code for a sequence diagram."""
    plantuml = "@startuml\n"
    
    participant_ids = {}
    
    for participant in sorted(participants):
        p_id = sanitize_id(participant)
        participant_ids[participant] = p_id
        plantuml += f'participant "{participant}" as {p_id}\n'
    
    plantuml += "\n"
    
    for interaction in interactions:
        modified_interaction = interaction
        for participant, p_id in participant_ids.items():
            modified_interaction = re.sub(r'\b' + re.escape(participant) + r'\b', p_id, modified_interaction)
        plantuml += modified_interaction + "\n"
    
    plantuml += "@enduml"
    return plantuml

def build_class_plantuml(classes, methods, relationships) -> str:
    """Build PlantUML code for a class diagram."""
    plantuml = "@startuml\n"
    
    class_ids = {}
    
    for class_name, attributes in classes.items():
        class_id = sanitize_id(class_name)
        class_ids[class_name] = class_id
        plantuml += f'class "{class_name}" as {class_id} {{\n'
        
        for attr in sorted(attributes):
            if isinstance(attr, str) and ':' not in attr:
                plantuml += f"  -{attr} : String\n"
            else:
                plantuml += f"  -{attr}\n"
        
        for method in sorted(methods.get(class_name, [])):
            plantuml += f"  {method}\n"
        
        plantuml += "}\n\n"
    
    for source, target, rel_type in relationships:
        if source in class_ids and target in class_ids:
            source_id = class_ids[source]
            target_id = class_ids[target]
            
            if rel_type == 'extends':
                plantuml += f"{source_id} --|> {target_id}\n"
            elif rel_type == 'implements':
                plantuml += f"{source_id} ..|> {target_id}\n"
            else:
                plantuml += f"{source_id} --> {target_id} : {rel_type}\n"
    
    plantuml += "@enduml"
    return plantuml