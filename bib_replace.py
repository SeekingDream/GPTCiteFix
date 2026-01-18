import bibtexparser
import json
import requests
from urllib.parse import quote
import logging
import argparse
from tqdm import tqdm
import time  # Added for rate limiting

# --- ARGUMENT PARSING ---
# (Existing parser code remains the same)
parser = argparse.ArgumentParser(description="Update BibTeX entries using DBLP.")
parser.add_argument("--bib_file", default="old.bib", help="Path to the input BibTeX file")
parser.add_argument("--output_file", default="output.bib", help="Path to save the updated BibTeX file")
parser.add_argument("--log_file", default="log.txt", help="Path for the log file")
args = parser.parse_args()

BIB_FILE = args.bib_file
OUTPUT_BIB_FILE = args.output_file
LOG_FILE = args.log_file

REVERSED_KEYS = {"author", "booktitle", "doi", "title", "year", 'ID', 'ENTRYTYPE'}

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def read_bib_file(bib_file):
    with open(bib_file, encoding="utf-8") as f:
        bib_database = bibtexparser.load(f)
    return [dict(entry) for entry in bib_database.entries]


# --- UPDATED QUERY FUNCTION WITH BACKOFF ---
def query_dblp(title, max_retries=5):
    """
    Query DBLP for a paper title with exponential backoff for 429 errors.
    """
    search_url = f"https://dblp.org/search/publ/api?q={quote(title)}&format=json"

    for attempt in range(max_retries):
        try:
            # Mandatory polite delay (DBLP prefers < 1 request per second)
            time.sleep(1.0)

            resp = requests.get(search_url)

            if resp.status_code == 429:
                wait_time = (2 ** attempt) + 1
                logging.warning(
                    f"Rate limited (429). Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue

            resp.raise_for_status()
            data = resp.json()
            hits = data['result']['hits'].get('hit')

            if not hits:
                return None

            dblp_key = hits[0]['info']['key']
            bib_url = f"https://dblp.org/rec/{dblp_key}.bib"

            # Fetch the BibTeX with the same retry logic implicit in the next loop if needed,
            # but usually, if the search works, the direct link works.
            bib_resp = requests.get(bib_url)
            if bib_resp.status_code == 200:
                parsed_bib = bibtexparser.loads(bib_resp.text)
                if parsed_bib.entries:
                    return dict(parsed_bib.entries[0])

            return None

        except Exception as e:
            logging.error(f"Error querying DBLP for {title}: {e}")
            # If it's a connection error, we might want to retry
            time.sleep(2)

    return None


# --- STEP 3: COMPARE AND LOG DIFFERENCES ---
def compare_entries(old_entry, new_entry):
    differences = {}
    ignored_keys = ['ID', 'ENTRYTYPE']
    for key, value in new_entry.items():
        if key not in ignored_keys:
            old_val = str(old_entry.get(key, "")).strip("{} ")
            new_val = str(value).strip("{} ")
            if old_val != new_val:
                differences[key] = {"old": old_entry.get(key), "new": value}
    return differences


def main():
    old_entries = read_bib_file(BIB_FILE)
    updated_entries = []

    changed_ids, unchanged_ids, no_title_ids, not_found_ids = [], [], [], []

    print(f"Processing {len(old_entries)} entries. Please wait...")
    for entry in tqdm(old_entries):
        title = entry.get("title")
        entry_id = entry.get('ID')

        if not title:
            no_title_ids.append(entry_id)
            updated_entries.append(entry)
            continue

        new_entry = query_dblp(title)
        if new_entry:
            # Filter keys based on your REVERSED_KEYS list
            filtered_new = {k: new_entry[k] for k in REVERSED_KEYS if k in new_entry}

            diff = compare_entries(entry, filtered_new)
            filtered_new['ID'] = entry_id

            if diff:
                changed_ids.append(entry_id)
                updated_entries.append(filtered_new)
            else:
                unchanged_ids.append(entry_id)
                updated_entries.append(entry)
        else:
            not_found_ids.append(entry_id)
            updated_entries.append(entry)

    # --- LOG SUMMARY ---
    # (Existing logging and file writing code remains the same)
    bib_database = bibtexparser.bibdatabase.BibDatabase()
    bib_database.entries = updated_entries
    with open(OUTPUT_BIB_FILE, "w", encoding="utf-8") as f:
        bibtexparser.dump(bib_database, f)

    print(f"\nDone! Updated: {len(changed_ids)}, Unchanged: {len(unchanged_ids)}, Not Found: {len(not_found_ids)}")


if __name__ == "__main__":
    main()