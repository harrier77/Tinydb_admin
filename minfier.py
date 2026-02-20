import json
import sys
import argparse

def minify_json(input_path, output_path):
    """
    Legge un file JSON (anche con caratteri corrotti) e lo salva in formato minificato.
    """
    try:
        # Usiamo 'surrogateescape' in lettura per catturare i byte orfani senza crash
        with open(input_path, 'r', encoding='utf-8', errors='surrogateescape') as f_in:
            data = json.load(f_in)
        
        # Scriviamo con 'replace' per garantire che il file finale sia UTF-8 valido
        with open(output_path, 'w', encoding='utf-8', errors='replace') as f_out:
            json.dump(data, f_out, separators=(',', ':'), ensure_ascii=False)
            
        print(f"Successo! File minificato salvato in: {output_path}")
        
    except FileNotFoundError:
        print(f"Errore: Il file '{input_path}' non è stato trovato.")
    except json.JSONDecodeError as e:
        print(f"Errore nel formato JSON: {e}")
    except Exception as e:
        print(f"Erro e imprevisto: {e}")

if __name__ == "__main__":
    # Configurazione degli argomenti da riga di comando
    parser = argparse.ArgumentParser(description="Minifica file JSON gestendo errori di codifica Unicode.")
    parser.add_argument("input", help="Percorso del file JSON originale")
    parser.add_argument("output", help="Percorso del file JSON minificato da creare")
    
    args = parser.parse_args()
    
    minify_json(args.input, args.output)