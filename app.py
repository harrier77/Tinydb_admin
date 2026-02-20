from flask import Flask, render_template, jsonify, request, session, redirect, url_for, flash
from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage
from tinydb.table import Table
import json
import os
import glob
from json_splitter import split_json_structure

class UTF8JSONStorage(JSONStorage):
    """Storage che forza l'encoding UTF-8 per supportare caratteri speciali"""
    def __init__(self, path, **kwargs):
        kwargs['encoding'] = 'utf-8'
        super().__init__(path, **kwargs)

class StringIdTable(Table):
    """Tabella che accetta ID stringa invece di numerici"""
    document_id_class = str

class CustomTinyDB(TinyDB):
    """TinyDB che usa sempre StringIdTable per tutte le tabelle"""
    table_class = StringIdTable

class DocumentWithId(dict):
    """Documento con attributo doc_id per compatibilità con TinyDB"""
    def __init__(self, data, doc_id, filename=None):
        super().__init__(data)
        self.doc_id = doc_id
        self.filename = filename

class SplitDirectoryTable:
    """Tabella che contiene tutti i documenti dalla directory splittata"""
    def __init__(self, directory_path, table_name):
        self.directory = directory_path
        self.table_name = table_name
        self._documents = None
        self._load_documents()
    
    def _load_documents(self):
        """Carica tutti i documenti JSON dalla directory"""
        self._documents = []
        doc_id = 1
        if os.path.exists(self.directory):
            for f in sorted(os.listdir(self.directory)):
                if f.endswith('.json'):
                    file_path = os.path.join(self.directory, f)
                    filename = os.path.splitext(f)[0]
                    try:
                        with open(file_path, 'r', encoding='utf-8') as file:
                            content = file.read().strip()
                            if content:
                                data = json.loads(content)
                                if isinstance(data, dict):
                                    self._documents.append(DocumentWithId(data, doc_id, filename))
                                    doc_id += 1
                                elif isinstance(data, list):
                                    for item in data:
                                        if isinstance(item, dict):
                                            self._documents.append(DocumentWithId(item, doc_id, filename))
                                            doc_id += 1
                    except (json.JSONDecodeError, FileNotFoundError) as e:
                        print(f"Errore caricamento {file_path}: {e}")
    
    def all(self):
        """Restituisce tutti i documenti come lista"""
        return self._documents if self._documents is not None else []
    
    def get(self, doc_id=None):
        """Restituisce un documento per ID (doc_id può essere indice o _id)"""
        documents = self.all()
        # Cerca per doc_id (indice numerico basato su 1)
        if isinstance(doc_id, int):
            for doc in documents:
                if doc.doc_id == doc_id:
                    return doc
        # Cerca per campo _id
        for doc in documents:
            if doc.get('_id') == doc_id:
                return doc
        return None

class SplitDirectoryDB:
    """Database TinyDB-like per directory splittate"""
    def __init__(self, directory_path):
        self.directory = directory_path
        self.root_config = self._load_root_config()
        tables_subdir = self.root_config.get('path', '')
        if tables_subdir:
            if tables_subdir.startswith('..'):
                parent_dir = os.path.dirname(os.path.abspath(directory_path))
                self.tables_path = os.path.normpath(os.path.join(parent_dir, tables_subdir))
            else:
                self.tables_path = os.path.join(directory_path, tables_subdir)
        else:
            self.tables_path = directory_path
        self._table_name = tables_subdir if tables_subdir else 'default'
        self._table_cache = {}
    
    def _load_root_config(self):
        """Carica la configurazione da root.json"""
        root_file = os.path.join(self.directory, 'root.json')
        try:
            with open(root_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {'path': ''}
    
    def tables(self):
        """Restituisce la lista dei nomi delle tabelle disponibili"""
        return [os.path.basename(self.directory)]
    
    def table(self, name):
        """Restituisce la tabella che contiene tutti i documenti dalla directory"""
        if name not in self._table_cache:
            self._table_cache[name] = SplitDirectoryTable(self.tables_path, name)
        return self._table_cache[name]

app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.template_filter('tojson_pretty')
def tojson_pretty(value):
    return json.dumps(value, indent=2, ensure_ascii=False)

def get_available_databases():
    """Ritorna la lista di tutti i file JSON e directory splittate nella directory corrente"""
    databases = []
    
    # File JSON singoli
    json_files = glob.glob('*.json')
    databases.extend(json_files)
    
    # Directory splittate (contengono root.json)
    for item in os.listdir('.'):
        if os.path.isdir(item):
            root_json = os.path.join(item, 'root.json')
            if os.path.exists(root_json):
                databases.append(item)
    
    return sorted(databases)

def get_db():
    """Restituisce l'istanza del database selezionato (file singolo o directory splittata)"""
    db_path = session.get('current_db', 'database.json')
    
    # Verifica se è una directory splittata
    if os.path.isdir(db_path):
        root_json = os.path.join(db_path, 'root.json')
        if os.path.exists(root_json):
            return SplitDirectoryDB(db_path)
    
    # Altrimenti è un file singolo
    # Verifica se il file esiste e se è in formato TinyDB valido
    if os.path.exists(db_path):
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Se è una lista (JSON semplice), convertilo in formato TinyDB
            if isinstance(data, list):
                # Crea una tabella "_default" con i documenti
                tinydb_data = {"_default": {}}
                for i, doc in enumerate(data, 1):
                    tinydb_data["_default"][str(i)] = doc
                
                # Salva nel formato TinyDB
                with open(db_path, 'w', encoding='utf-8') as f:
                    json.dump(tinydb_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Errore nella conversione del database: {e}")
    
    return CustomTinyDB(db_path, storage=UTF8JSONStorage)

def get_array_fields(doc):
    """Ritorna i campi del documento che sono array di oggetti (sottocollezioni)"""
    arrays = {}
    for key, value in doc.items():
        if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
            arrays[key] = value
    return arrays

def get_field_types(doc):
    """Ritorna un dizionario con il tipo di ogni campo del documento"""
    field_types = {}
    for key, value in doc.items():
        if isinstance(value, dict):
            field_types[key] = 'object'
        elif isinstance(value, list):
            field_types[key] = 'array'
        else:
            field_types[key] = 'simple'
    return field_types

def build_breadcrumb(path, current_doc=None):
    """
    Costruisce la lista breadcrumb [(url, label), ...] dal path /browse/...
    Nasconde 'doc' e 'field' nei label, ma mantiene 'doc' nell'URL.
    Usa 'nome' del documento se disponibile.
    """
    if not path:
        return [('/', 'Home')]
    
    parts = path.split('/')
    breadcrumb = [('/', 'Home')]
    
    current_path_parts = []
    i = 0
    
    while i < len(parts):
        part = parts[i]
        if not part:
            i += 1
            continue
        
        # Aggiungi la parte al path corrente (per URL)
        current_path_parts.append(part)
        
        # Salta 'doc' e 'field' solo per la LABEL (non per l'URL)
        if part in ('doc', 'field'):
            i += 1
            continue
        
        # Costruisci l'URL corretto
        current_url = '/browse/' + '/'.join(current_path_parts)
        
        # Determina la label
        if i == 0:
            # Prima parte: nome collezione
            label = part
        elif i >= 2 and parts[i-1] == 'doc':
            # Dopo 'doc' viene l'ID - cerca 'nome' nel documento corrente
            if current_doc and isinstance(current_doc, dict) and 'nome' in current_doc:
                label = current_doc['nome']
            else:
                label = f'#{part}'
        else:
            # Campi, array names, index, ecc.
            label = part
        
        # L'ultimo elemento non ha URL (è la pagina corrente)
        if i == len(parts) - 1:
            breadcrumb.append((None, label))
        else:
            breadcrumb.append((current_url, label))
        
        i += 1
    
    return breadcrumb

@app.route('/')
def index():
    db = get_db()
    tables = list(db.tables())
    databases = get_available_databases()
    current_db = session.get('current_db', 'database.json')
    return render_template('base.html', tables=tables, databases=databases, current_db=current_db)

@app.route('/select-db', methods=['POST'])
def select_db():
    """Seleziona un nuovo database"""
    db_file = request.form.get('database')
    if db_file and os.path.exists(db_file):
        session['current_db'] = db_file
    return redirect(url_for('index'))

@app.route('/split-json', methods=['POST'])
def split_json():
    """Processa un file JSON e crea una versione splittata minificata"""
    input_file = request.form.get('input_file')
    
    if not input_file:
        flash('Nessun file selezionato', 'error')
        return redirect(url_for('index'))
    
    if not os.path.exists(input_file):
        flash(f'File non trovato: {input_file}', 'error')
        return redirect(url_for('index'))
    
    if not input_file.endswith('.json'):
        flash('Il file deve essere un JSON', 'error')
        return redirect(url_for('index'))
    
    # Crea il nome della directory di output (senza estensione)
    output_dir = os.path.splitext(input_file)[0]
    
    # Se la directory esiste già, aggiungi un numero
    counter = 1
    original_output_dir = output_dir
    while os.path.exists(output_dir):
        output_dir = f"{original_output_dir}_{counter}"
        counter += 1
    
    try:
        # Esegui lo splitting con minify=True
        result = split_json_structure(
            input_file=input_file,
            output_dir=output_dir,
            max_depth=2,
            threshold=2,
            minify=True
        )
        
        flash(f'File splittato con successo! Creati {len(result["files_created"])} file in {output_dir}', 'success')
        
        # Seleziona automaticamente il nuovo database splittato
        session['current_db'] = output_dir
        
    except Exception as e:
        flash(f'Errore durante lo splitting: {str(e)}', 'error')
    
    return redirect(url_for('index'))

@app.route('/browse/<path:path>')
def browse(path):
    print(f"\n{'='*60}")
    print(f"BROWSE PATH: {path}")
    print(f"{'='*60}")
    
    db = get_db()
    tables = list(db.tables())
    
    # Parsing del path
    parts = path.split('/')
    
    # Usa il nome del database dalla sessione se disponibile
    current_db_name = session.get('current_db', '')
    if current_db_name and os.path.isdir(current_db_name):
        current_table = current_db_name
    else:
        current_table = parts[0] if parts else None
    current_doc_id = None
    current_doc = None
    root_doc_id = None
    root_doc = None
    documents = []
    nested_levels = []
    table = None
    
    
    # Carica documenti della tabella
    if current_table:
        table = db.table(current_table)
        documents = table.all()
    
    # Analisi del path
    if len(parts) >= 2 and table is not None:
        if parts[1] == 'doc' and len(parts) >= 3:
            # Navigazione: /tabella/doc/id
            try:
                current_doc_id = int(parts[2])
            except:
                current_doc_id = parts[2]
            
            current_doc = table.get(doc_id=current_doc_id)
            
            # Salva l'ID e il documento root per costruire URL corretti e navigare gli array
            root_doc_id = current_doc_id
            root_doc = current_doc
            
            # Controlla se è richiesto un elemento di un array (supporta array annidati)
            if current_doc and isinstance(current_doc, dict) and len(parts) >= 5:
                current_array_doc = current_doc
                current_array_name = None
                current_array_index = None
                part_idx = 3
                
                # Naviga ricorsivamente attraverso array annidati
                base_path_parts = []
                while part_idx < len(parts) - 1:
                    array_name = parts[part_idx]
                    array_data = current_array_doc.get(array_name) if hasattr(current_array_doc, 'get') else None
                    
                    if isinstance(array_data, list) and part_idx + 1 < len(parts):
                        try:
                            array_index = int(parts[part_idx + 1])
                            if 0 <= array_index < len(array_data):
                                array_item = array_data[array_index]
                                item_field_types = get_field_types(array_item) if isinstance(array_item, dict) else {}
                                
                                # Costruisci il base_path per questo livello
                                base_path_parts.append(f"{array_name}/{array_index}")
                                base_path = '/'.join(base_path_parts)
                                
                                nested_levels.append({
                                    'type': 'array_document',
                                    'index': array_index,
                                    'document': array_item,
                                    'array_name': array_name,
                                    'field_types': item_field_types,
                                    'base_path': base_path
                                })
                                
                                # Prepara per il prossimo livello
                                current_array_doc = array_item
                                current_array_name = array_name
                                current_array_index = array_index
                                part_idx += 2  # Salta nome e indice array
                            else:
                                break
                        except (ValueError, IndexError):
                            break
                    else:
                        break
                
                # Salva il documento root originale prima di aggiornare current_doc
                root_doc = current_doc
                
                # Aggiorna current_doc all'elemento array più interno per mostrarne i campi
                if nested_levels:
                    last_level = nested_levels[-1]
                    if last_level['type'] == 'array_document':
                        current_doc = last_level['document']
                        current_doc_id = last_level['document'].get('_id', f"{last_level['array_name']}[{last_level['index']}]")
                
                # Se rimangono parti dopo aver navigato gli array, sono campi
                if part_idx < len(parts) and isinstance(current_array_doc, dict):
                    field_name = parts[part_idx]
                    field_value = current_array_doc.get(field_name)
                    
                    if field_value is not None:
                        field_type = 'simple'
                        if isinstance(field_value, dict):
                            field_type = 'object'
                        elif isinstance(field_value, list):
                            field_type = 'array'
                        
                        nested_levels.append({
                            'type': 'field_value',
                            'field_name': field_name,
                            'field_value': field_value,
                            'field_type': field_type,
                            'parent_name': f"{current_array_name}[{current_array_index}]" if current_array_name else f"Documento {current_doc_id}"
                        })
                
                # Navigazione nei campi del documento principale (non array)
                if len(parts) >= 5 and parts[3] == 'field':
                    field_path = parts[4:]
                    field_name = field_path[0]
                    array_item_processed = False
                    
                    # Verifica se il primo campo è un array del documento
                    if isinstance(current_doc, dict) and field_name in current_doc:
                        field_data = current_doc[field_name]
                        if isinstance(field_data, list) and len(field_path) >= 2:
                            # È un array con possibile indice
                            try:
                                array_index = int(field_path[1])
                                if 0 <= array_index < len(field_data):
                                    array_item = field_data[array_index]
                                    item_field_types = get_field_types(array_item) if isinstance(array_item, dict) else {}
                                    nested_levels.append({
                                        'type': 'array_document',
                                        'index': array_index,
                                        'document': array_item,
                                        'array_name': field_name,
                                        'field_types': item_field_types
                                    })
                                    array_item_processed = True
                                    
                                    # Se ci sono altri livelli (campi dell'elemento array)
                                    if len(field_path) >= 3:
                                        subfield_name = field_path[2]
                                        subfield_value = array_item.get(subfield_name) if isinstance(array_item, dict) else None
                                        if subfield_value is not None:
                                            # Determina il tipo
                                            subfield_type = 'simple'
                                            if isinstance(subfield_value, dict):
                                                subfield_type = 'object'
                                            elif isinstance(subfield_value, list):
                                                subfield_type = 'array'
                                            
                                            nested_levels.append({
                                                'type': 'field_value',
                                                'field_name': subfield_name,
                                                'field_value': subfield_value,
                                                'field_type': subfield_type,
                                                'parent_name': f"{field_name}[{array_index}]"
                                            })
                            except (ValueError, IndexError):
                                pass
                    
                    # Naviga nel path dei campi (caso normale, solo se non è stato processato come array)
                    if not array_item_processed:
                        current_value = current_doc
                        for i, field in enumerate(field_path):
                            if isinstance(current_value, dict) and field in current_value:
                                current_value = current_value[field]
                            elif isinstance(current_value, list) and field.isdigit():
                                idx = int(field)
                                if 0 <= idx < len(current_value):
                                    current_value = current_value[idx]
                                else:
                                    current_value = None
                                    break
                            else:
                                current_value = None
                                break
                        
                        if current_value is not None:
                            # Determina il tipo di campo
                            field_type = 'simple'
                            if isinstance(current_value, dict):
                                field_type = 'object'
                            elif isinstance(current_value, list):
                                field_type = 'array'
                            
                            nested_levels.append({
                                'type': 'field_value',
                                'field_name': field_name,
                                'field_value': current_value,
                                'field_type': field_type,
                                'parent_name': f"Documento {current_doc_id}"
                            })
    
    # Trova array di oggetti nel documento corrente (per mostrare come sottocollezioni)
    array_collections = {}
    field_types = {}
    if current_doc:
        array_collections = get_array_fields(current_doc)
        field_types = get_field_types(current_doc)
    
    # Rileva se siamo su un item di array finale
    # È un array item solo se l'ultima parte è un numero preceduto da un nome (non 'doc' o 'field')
    # Es: /collezione/doc/4/personaggi/0 → è array item (0 è indice di 'personaggi')
    # Es: /collezione/doc/4 → NON è array item (4 è doc_id)
    is_array_item = False
    item_index = None
    item_parent_name = None
    current_array = None  # Lista completa degli elementi array
    current_array_name = None
    
    if parts and parts[-1].isdigit() and len(parts) >= 2:
        prev_part = parts[-2]
        # È array item solo se il precedente NON è 'doc' o 'field'
        if prev_part not in ('doc', 'field'):
            is_array_item = True
            try:
                item_index = int(parts[-1])
                item_parent_name = prev_part
            # Estrai l'array completo dal documento root originale (non da current_doc che è già l'elemento)
                if root_doc and isinstance(root_doc, dict):
                    # Cerca l'array nel documento root, navigando attraverso i livelli annidati se necessario
                    if nested_levels and len(nested_levels) > 1:
                        # Se ci sono livelli intermedi, l'array è nell'ultimo livello nested (parent dell'elemento corrente)
                        parent_level = nested_levels[-2]  # Il parent dell'elemento corrente
                        current_array = parent_level['document'].get(item_parent_name)
                    else:
                        # Altrimenti l'array è direttamente nel documento root
                        current_array = root_doc.get(item_parent_name)
                    current_array_name = item_parent_name
            except (ValueError, IndexError):
                is_array_item = False
    
    # Genera breadcrumb con accesso al documento corrente per il nome
    breadcrumb = build_breadcrumb(path, current_doc)
    
    databases = get_available_databases()
    current_db = session.get('current_db', 'database.json')
    
    # Debug finale
    print(f"\n--- STATO FINALE ---")
    print(f"current_table: {current_table}")
    print(f"current_doc_id: {current_doc_id}")
    print(f"current_doc type: {type(current_doc)}")
    if current_doc and isinstance(current_doc, dict):
        print(f"current_doc _id: {current_doc.get('_id')}")
    else:
        print(f"current_doc: {current_doc}")
    print(f"nested_levels count: {len(nested_levels)}")
    for i, level in enumerate(nested_levels):
        doc_info = level.get('document')
        doc_id = doc_info.get('_id') if doc_info and isinstance(doc_info, dict) else 'N/A'
        print(f"  level {i}: type={level.get('type')}, array_name={level.get('array_name')}, doc_id={doc_id}")
    print(f"is_array_item: {is_array_item}")
    print(f"item_parent_name: {item_parent_name}")
    print(f"--- FINE ---\n")
    
    return render_template('browser.html',
                         tables=tables,
                         current_table=current_table,
                         current_doc_id=current_doc_id,
                         root_doc_id=root_doc_id,
                         current_doc=current_doc,
                         documents=documents,
                         nested_levels=nested_levels,
                         array_collections=array_collections,
                         breadcrumb=breadcrumb,
                         is_array_item=is_array_item,
                         item_index=item_index,
                         item_parent_name=item_parent_name,
                         current_array=current_array,
                         current_array_name=current_array_name,
                         databases=databases,
                         current_db=current_db,
                         field_types=field_types)

# Route API
@app.route('/api/tables')
def api_tables():
    db = get_db()
    return jsonify(list(db.tables()))

@app.route('/api/table/<path:table_name>')
def api_table(table_name):
    db = get_db()
    table = db.table(table_name)
    documents = table.all()
    return jsonify(documents)

@app.route('/api/table/<path:table_name>/doc/<doc_id>')
def api_document(table_name, doc_id):
    db = get_db()
    table = db.table(table_name)
    try:
        doc_id = int(doc_id)
    except:
        pass
    doc = table.get(doc_id=doc_id)
    if doc:
        return jsonify(doc)
    return jsonify({'error': 'Document not found'}), 404

@app.route('/api/table/<path:table_name>/doc/<doc_id>/update', methods=['POST'])
def update_field(table_name, doc_id):
    """Aggiorna un campo semplice (stringa o numero) in un documento"""
    db = get_db()
    
    # Parse request data
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Dati mancanti'}), 400
    
    field_path = data.get('field_path')
    value = data.get('value')
    value_type = data.get('value_type', 'string')
    
    if field_path is None or value is None:
        return jsonify({'error': 'field_path e value sono richiesti'}), 400
    
    # Validazione tipo
    if value_type == 'number':
        try:
            # Prova a convertire in numero
            if '.' in str(value):
                value = float(value)
            else:
                value = int(value)
        except (ValueError, TypeError):
            return jsonify({'error': 'Il valore deve essere un numero valido'}), 400
    else:
        value = str(value)
    
    # Ottieni il documento
    # Nota: con StringIdTable, doc_id sono stringhe (non convertire in int)
    # Prova prima come stringa, poi come int per retrocompatibilità
    doc_id_original = doc_id
    
    if isinstance(db, SplitDirectoryDB):
        # Gestione directory splittata
        table = db.table(table_name)
        
        # Prova a cercare il documento con doc_id come stringa o int
        doc = table.get(doc_id=doc_id)
        if not doc:
            # Prova come int se è una stringa numerica
            try:
                doc_id_int = int(doc_id)
                doc = table.get(doc_id=doc_id_int)
            except (ValueError, TypeError):
                pass
        
        if not doc:
            return jsonify({'error': 'Documento non trovato'}), 404
        
        # Trova il file JSON che contiene questo documento
        file_path = None
        doc_index = None
        for i, d in enumerate(table._documents):
            # Confronta sia come stringa che come int
            if str(d.doc_id) == str(doc_id) or d.doc_id == doc_id:
                # Usa il filename memorizzato nel documento
                if d.filename:
                    file_path = os.path.join(table.directory, f"{d.filename}.json")
                else:
                    file_path = os.path.join(table.directory, f"{i+1}.json")
                doc_index = i
                break
        
        if not file_path or not os.path.exists(file_path):
            return jsonify({'error': 'File documento non trovato'}), 404
        
        # Aggiorna il campo
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                file_data = json.load(f)
            
            # Se file_data è una lista, determina quale elemento modificare
            target_doc = file_data
            doc_index_for_array = None
            if isinstance(file_data, list):
                # Il doc_id è l'indice nella lista (1-based)
                doc_index_for_array = int(doc_id) - 1
                if 0 <= doc_index_for_array < len(file_data):
                    target_doc = file_data[doc_index_for_array]
                else:
                    return jsonify({'error': 'Indice documento non valido'}), 404
            
            # Naviga il path e aggiorna
            keys = field_path.split('.')
            current = target_doc
            
            for key in keys[:-1]:
                if key.isdigit():
                    key = int(key)
                if isinstance(current, dict) and key in current:
                    current = current[key]
                elif isinstance(current, list) and isinstance(key, int) and 0 <= key < len(current):
                    current = current[key]
                else:
                    return jsonify({'error': f'Path non valido: {field_path}'}), 400
            
            # Aggiorna il valore finale
            final_key = keys[-1]
            if final_key.isdigit():
                final_key = int(final_key)
            
            if isinstance(current, dict) and final_key in current:
                current[final_key] = value
            elif isinstance(current, list) and isinstance(final_key, int) and 0 <= final_key < len(current):
                current[final_key] = value
            else:
                return jsonify({'error': f'Campo non trovato: {final_key}'}), 400
            
            # Salva il file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(file_data, f, ensure_ascii=False, indent=2)
            
            # Ricarica i documenti in memoria
            table._load_documents()
            
            return jsonify({'success': True, 'message': 'Campo aggiornato'})
            
        except Exception as e:
            return jsonify({'error': f'Errore durante l\'aggiornamento: {str(e)}'}), 500
    
    else:
        # Gestione TinyDB normale
        table = db.table(table_name)
        
        # Prova a cercare il documento con doc_id come stringa o int
        doc = table.get(doc_id=doc_id)
        effective_doc_id = doc_id
        if not doc:
            # Prova come int se è una stringa numerica
            try:
                doc_id_int = int(doc_id)
                doc = table.get(doc_id=doc_id_int)
                if doc:
                    effective_doc_id = doc_id_int
            except (ValueError, TypeError):
                pass
        
        if not doc:
            return jsonify({'error': 'Documento non trovato'}), 404
        
        # Prepara l'update
        keys = field_path.split('.')
        
        # Costruisci l'oggetto update per TinyDB
        # TinyDB richiede un dizionario flat, quindi dobbiamo navigare manualmente
        try:
            # Carica il documento completo
            all_docs = table.all()
            target_doc = None
            for d in all_docs:
                # Confronta sia come stringa che come int
                if str(d.doc_id) == str(effective_doc_id) or d.doc_id == effective_doc_id:
                    target_doc = d
                    break
            
            if not target_doc:
                return jsonify({'error': 'Documento non trovato'}), 404
            
            # Naviga e aggiorna
            current = target_doc
            for key in keys[:-1]:
                if key.isdigit():
                    key = int(key)
                if isinstance(current, dict) and key in current:
                    current = current[key]
                elif isinstance(current, list) and isinstance(key, int) and 0 <= key < len(current):
                    current = current[key]
                else:
                    return jsonify({'error': f'Path non valido: {field_path}'}), 400
            
            # Aggiorna il valore finale
            final_key = keys[-1]
            if final_key.isdigit():
                final_key = int(final_key)
            
            if isinstance(current, dict) and final_key in current:
                current[final_key] = value
            elif isinstance(current, list) and isinstance(final_key, int) and 0 <= final_key < len(current):
                current[final_key] = value
            else:
                return jsonify({'error': f'Campo non trovato: {final_key}'}), 400
            
            # Usa TinyDB per aggiornare
            from tinydb.operations import set
            table.update(set(keys[0], target_doc[keys[0]]), doc_ids=[effective_doc_id])
            
            return jsonify({'success': True, 'message': 'Campo aggiornato'})
            
        except Exception as e:
            return jsonify({'error': f'Errore durante l\'aggiornamento: {str(e)}'}), 500

# Legacy routes per retrocompatibilità
@app.route('/table/<path:table_name>')
def view_table(table_name):
    return browse(table_name)

@app.route('/table/<path:table_name>/doc/<doc_id>')
def view_document(table_name, doc_id):
    return browse(f"{table_name}/doc/{doc_id}")

if __name__ == '__main__':
    app.run(debug=True, port=5000)
