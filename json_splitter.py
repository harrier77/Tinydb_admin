"""
JSON Structure Splitter

Questo modulo analizza la struttura di un file JSON e quando trova più di un elemento
al primo o secondo livello di nidificazione, suddivide gli elementi in file separati.

Uso come modulo:
    from json_splitter import split_json_structure
    split_json_structure('input.json', 'output_dir')

Uso standalone:
    python json_splitter.py input.json output_dir
"""

import json
import os
import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union


def minify_json_data(data: Any) -> str:
    """
    Converte i dati in formato JSON minificato.
    Rimuove spazi e indentazione per ridurre la dimensione del file.
    
    Args:
        data: Dati da convertire in JSON
    
    Returns:
        Stringa JSON minificata
    """
    return json.dumps(data, separators=(',', ':'), ensure_ascii=False)


def _write_json_file(file_path: Path, data: Any, minify: bool = False) -> None:
    """
    Scrive i dati in un file JSON, con o senza formattazione.
    
    Args:
        file_path: Percorso del file da creare
        data: Dati da salvare
        minify: Se True, salva in formato minificato (senza indentazione)
    """
    if minify:
        with open(file_path, 'w', encoding='utf-8', errors='replace') as f:
            json.dump(data, f, separators=(',', ':'), ensure_ascii=False)
    else:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def split_json_structure(
    input_file: str,
    output_dir: str,
    max_depth: int = 2,
    threshold: int = 2,
    minify: bool = False
) -> Dict[str, Any]:
    """
    Analizza e suddivide la struttura di un file JSON.
    
    Args:
        input_file: Percorso al file JSON di input
        output_dir: Directory di output dove creare i file suddivisi
        max_depth: Profondità massima di analisi (default: 2)
        threshold: Soglia minima di elementi per la suddivisione (default: 2)
        minify: Se True, salva i file in formato minificato (default: False)
    
    Returns:
        Dizionario con informazioni sulla struttura analizzata e i file creati
    """
    # Carica il JSON
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Crea la directory di output se non esiste
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Analizza la struttura
    structure_info = {
        'root_name': output_path.name,
        'levels': [],
        'files_created': [],
        'directories_created': []
    }
    
    # Determina il nome base del file (senza estensione)
    input_name = Path(input_file).stem
    
    # Inizia l'analisi ricorsiva
    _process_level(
        data=data,
        output_dir=output_path,
        current_depth=0,
        max_depth=max_depth,
        threshold=threshold,
        parent_key=input_name,
        structure_info=structure_info,
        minify=minify
    )
    
    return structure_info


def _process_level(
    data: Any,
    output_dir: Path,
    current_depth: int,
    max_depth: int,
    threshold: int,
    parent_key: str,
    structure_info: Dict[str, Any],
    minify: bool = False
) -> Any:
    """
    Processa un livello della struttura JSON in modo ricorsivo.
    
    Args:
        minify: Se True, salva i file in formato minificato
    
    Returns:
        Il dato processato (modificato o non modificato)
    """
    # Se non è un dizionario, ritorna così com'è
    if not isinstance(data, dict):
        return data
    
    # Se abbiamo superato la profondità massima, ritorna così com'è
    if current_depth >= max_depth:
        return data
    
    keys = list(data.keys())
    num_elements = len(keys)
    
    # Se c'è un solo elemento al livello 0, scendi al livello 1
    if current_depth == 0 and num_elements == 1:
        single_key = keys[0]
        single_value = data[single_key]
        
        # Se il valore è un dizionario, analizza il livello successivo
        if isinstance(single_value, dict):
            sub_keys = list(single_value.keys())
            sub_count = len(sub_keys)
            
            # Se il livello 1 ha almeno 2 elementi, suddividi
            if sub_count >= threshold:
                # Crea la cartella per questo livello
                level_dir = output_dir / _sanitize_filename(single_key)
                level_dir.mkdir(parents=True, exist_ok=True)
                structure_info['directories_created'].append(str(level_dir))
                
                # Crea root.json che punta a questa cartella
                root_file = output_dir / 'root.json'
                _write_json_file(root_file, {"path": single_key}, minify)
                structure_info['files_created'].append(str(root_file))
                
                # Registra il livello
                structure_info['levels'].append({
                    'depth': 1,
                    'key': single_key,
                    'element_count': sub_count,
                    'action': 'split'
                })
                
                # Processa ogni sotto-elemento
                for sub_key, sub_value in single_value.items():
                    sub_file = level_dir / f"{_sanitize_filename(sub_key)}.json"
                    _write_json_file(sub_file, sub_value, minify)
                    structure_info['files_created'].append(str(sub_file))
                
                return None
            else:
                # Livello 1 ha meno di 2 elementi, scendi ancora
                structure_info['levels'].append({
                    'depth': 1,
                    'key': single_key,
                    'element_count': sub_count,
                    'action': 'continue'
                })
                return _process_level(
                    data=single_value,
                    output_dir=output_dir,
                    current_depth=1,
                    max_depth=max_depth,
                    threshold=threshold,
                    parent_key=single_key,
                    structure_info=structure_info,
                    minify=minify
                )
        else:
            # Il valore non è un dizionario, salva così com'è
            output_file = output_dir / f"{_sanitize_filename(single_key)}.json"
            _write_json_file(output_file, single_value, minify)
            structure_info['files_created'].append(str(output_file))
            return None
    
    # Se ci sono 2 o più elementi, suddividi al livello corrente
    elif num_elements >= threshold:
        structure_info['levels'].append({
            'depth': current_depth,
            'key': parent_key,
            'element_count': num_elements,
            'action': 'split'
        })
        
        # Se siamo al livello 0, crea una cartella e root.json
        if current_depth == 0:
            # Crea la cartella principale
            main_dir = output_dir / _sanitize_filename(parent_key)
            main_dir.mkdir(parents=True, exist_ok=True)
            structure_info['directories_created'].append(str(main_dir))
            
            # Crea root.json
            root_file = output_dir / 'root.json'
            _write_json_file(root_file, {"path": parent_key}, minify)
            structure_info['files_created'].append(str(root_file))
            
            # Salva ogni elemento come file separato
            for key, value in data.items():
                sub_file = main_dir / f"{_sanitize_filename(key)}.json"
                _write_json_file(sub_file, value, minify)
                structure_info['files_created'].append(str(sub_file))
        else:
            # Siamo a un livello intermedio, crea una sottocartella
            sub_dir = output_dir / _sanitize_filename(parent_key)
            sub_dir.mkdir(parents=True, exist_ok=True)
            structure_info['directories_created'].append(str(sub_dir))
            
            # Salva ogni elemento come file separato
            for key, value in data.items():
                sub_file = sub_dir / f"{_sanitize_filename(key)}.json"
                _write_json_file(sub_file, value, minify)
                structure_info['files_created'].append(str(sub_file))
        
        return None
    
    # Meno di 2 elementi e non è il caso speciale del livello 0 con 1 elemento
    else:
        structure_info['levels'].append({
            'depth': current_depth,
            'key': parent_key,
            'element_count': num_elements,
            'action': 'save_as_is'
        })
        
        # Salva il file così com'è
        output_file = output_dir / f"{_sanitize_filename(parent_key)}.json"
        _write_json_file(output_file, data, minify)
        structure_info['files_created'].append(str(output_file))
        
        return None


def _sanitize_filename(name: str) -> str:
    """
    Sanitizza una stringa per usarla come nome file/cartella.
    Rimuove o sostituisce caratteri non validi.
    """
    # Caratteri non validi nei nomi file Windows/Unix
    invalid_chars = '<>:"/\\|?*'
    
    # Sostituisci i caratteri non validi con underscore
    for char in invalid_chars:
        name = name.replace(char, '_')
    
    # Rimuovi spazi iniziali e finali
    name = name.strip()
    
    # Se il nome è vuoto, usa un default
    if not name:
        name = 'unnamed'
    
    return name


def analyze_json_structure(
    input_file: str,
    max_depth: int = 2
) -> Dict[str, Any]:
    """
    Analizza la struttura di un file JSON senza creare file.
    Utile per vedere come verrebbe suddiviso.
    
    Args:
        input_file: Percorso al file JSON
        max_depth: Profondità massima di analisi
    
    Returns:
        Dizionario con l'analisi della struttura
    """
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    analysis = {
        'total_keys_level_0': 0,
        'keys_level_0': [],
        'has_single_root': False,
        'level_1_analysis': {}
    }
    
    if isinstance(data, dict):
        keys = list(data.keys())
        analysis['total_keys_level_0'] = len(keys)
        analysis['keys_level_0'] = keys
        
        if len(keys) == 1:
            analysis['has_single_root'] = True
            root_key = keys[0]
            root_value = data[root_key]
            
            if isinstance(root_value, dict):
                sub_keys = list(root_value.keys())
                analysis['level_1_analysis'] = {
                    'root_key': root_key,
                    'total_keys_level_1': len(sub_keys),
                    'keys_level_1': sub_keys,
                    'would_split': len(sub_keys) >= 2
                }
            else:
                analysis['level_1_analysis'] = {
                    'root_key': root_key,
                    'type': type(root_value).__name__,
                    'would_split': False
                }
        else:
            analysis['would_split'] = len(keys) >= 2
    
    return analysis


def main():
    """Funzione principale per l'uso da riga di comando."""
    parser = argparse.ArgumentParser(
        description='Suddivide la struttura di un file JSON in file separati '
                   'quando ci sono 2+ elementi al primo o secondo livello.'
    )
    
    parser.add_argument(
        'input_file',
        help='Percorso al file JSON di input'
    )
    
    parser.add_argument(
        'output_dir',
        help='Directory di output dove creare i file suddivisi'
    )
    
    parser.add_argument(
        '--max-depth',
        type=int,
        default=2,
        help='Profondità massima di analisi (default: 2)'
    )
    
    parser.add_argument(
        '--threshold',
        type=int,
        default=2,
        help='Soglia minima di elementi per la suddivisione (default: 2)'
    )
    
    parser.add_argument(
        '--analyze-only',
        action='store_true',
        help='Solo analizza la struttura senza creare file'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Output dettagliato'
    )
    
    parser.add_argument(
        '--minify',
        action='store_true',
        help='Salva i file JSON in formato minificato (senza indentazione)'
    )
    
    args = parser.parse_args()
    
    # Verifica che il file di input esista
    if not os.path.exists(args.input_file):
        print(f"Errore: Il file '{args.input_file}' non esiste.")
        return 1
    
    try:
        if args.analyze_only:
            # Solo analisi
            print(f"Analisi del file: {args.input_file}")
            print("-" * 50)
            
            analysis = analyze_json_structure(args.input_file, args.max_depth)
            
            print(f"Chiavi al livello 0: {analysis['total_keys_level_0']}")
            print(f"Nomi chiavi: {', '.join(analysis['keys_level_0'])}")
            
            if analysis['has_single_root']:
                print(f"\nRoot unico: {analysis['keys_level_0'][0]}")
                if 'total_keys_level_1' in analysis['level_1_analysis']:
                    l1 = analysis['level_1_analysis']
                    print(f"Chiavi al livello 1: {l1['total_keys_level_1']}")
                    print(f"Nomi chiavi livello 1: {', '.join(l1['keys_level_1'][:5])}", end="")
                    if len(l1['keys_level_1']) > 5:
                        print(f" ... e altri {len(l1['keys_level_1']) - 5}")
                    else:
                        print()
                    print(f"\nVerrà suddiviso: {'Sì' if l1['would_split'] else 'No'}")
            else:
                if analysis.get('would_split'):
                    print(f"\nVerrà suddiviso: Sì (al livello 0)")
                else:
                    print(f"\nVerrà suddiviso: No (meno di {args.threshold} elementi)")
        else:
            # Esegui la suddivisione
            if args.verbose:
                print(f"Elaborazione di: {args.input_file}")
                print(f"Output in: {args.output_dir}")
                print("-" * 50)
            
            result = split_json_structure(
                input_file=args.input_file,
                output_dir=args.output_dir,
                max_depth=args.max_depth,
                threshold=args.threshold,
                minify=args.minify
            )
            
            if args.verbose:
                print(f"\nLivelli analizzati:")
                for level in result['levels']:
                    print(f"  Livello {level['depth']}: {level['key']} "
                          f"({level['element_count']} elementi) - {level['action']}")
                
                print(f"\nDirectory create: {len(result['directories_created'])}")
                for d in result['directories_created']:
                    print(f"  [DIR] {d}")
                
                print(f"\nFile creati: {len(result['files_created'])}")
                for f in result['files_created']:
                    print(f"  [FILE] {f}")
            else:
                print(f"✓ Suddivisione completata")
                print(f"  Directory: {len(result['directories_created'])}")
                print(f"  File: {len(result['files_created'])}")
                print(f"  Output: {args.output_dir}")
        
        return 0
        
    except json.JSONDecodeError as e:
        print(f"Errore: Il file non è un JSON valido. {e}")
        return 1
    except Exception as e:
        print(f"Errore durante l'elaborazione: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
