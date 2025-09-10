import os, csv
from chromadb import Client
from chromadb.config import Settings

ROOT = os.path.dirname(__file__)
DOCS = os.path.join(ROOT, "docs")
DB = os.path.join(ROOT, "data", "chroma")
os.makedirs(DB, exist_ok=True)

client = Client(Settings(persist_directory=DB))
coll = client.get_or_create_collection("engineering")

def add_doc(path, doc_id_prefix):
    with open(path) as f:
        txt = f.read().strip()
    coll.add(documents=[txt], ids=[doc_id_prefix+os.path.basename(path)])

add_doc(os.path.join(DOCS,"procedures.txt"), "eng-")
add_doc(os.path.join(DOCS,"syllabus.txt"), "eng-")

faq = os.path.join(DOCS,"faq.csv")
if os.path.exists(faq):
    with open(faq) as f:
        for i,row in enumerate(csv.reader(f)):
            if not row: continue
            q,a = row[0], (row[1] if len(row)>1 else "")
            coll.add(documents=[f"Q: {q}\nA: {a}"], ids=[f"eng-faq-{i}"])

print("Ingest complete.")
