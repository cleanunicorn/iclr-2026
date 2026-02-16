from pymongo import MongoClient
import shutil
import os

def main():
    # Clean DB
    try:
        client = MongoClient("mongodb://localhost:27017/")
        db = client["iclr-2026"]
        result = db.papers.delete_many({})
        print(f"Deleted {result.deleted_count} documents from MongoDB.")
    except Exception as e:
        print(f"Error cleaning DB: {e}")

    # Clean PDFs
    pdf_dir = "pdfs"
    if os.path.exists(pdf_dir):
        try:
            shutil.rmtree(pdf_dir)
            print(f"Removed {pdf_dir} directory.")
            os.makedirs(pdf_dir)
            print(f"Recreated {pdf_dir} directory.")
        except Exception as e:
            print(f"Error cleaning PDFs: {e}")

if __name__ == "__main__":
    main()
