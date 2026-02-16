from openreview.api import OpenReviewClient
from dotenv import load_dotenv
import os
import pprint

load_dotenv()

def main():
    try:
        client = OpenReviewClient(
            baseurl='https://api2.openreview.net',
            username=os.getenv('OPENREVIEW_USERNAME'),
            password=os.getenv('OPENREVIEW_PASSWORD')
        )
        
        # Test author with known profile
        # Using one from previous Top 20: ~Evgeny_Burnaev1 ? Need to find ID.
        # Let's search for "Yoshua Bengio" likely to have awards.
        
        # In V2, get_profiles uses emails or ids. Search by name is complex.
        # But we can try to fetch a specific ID directly if we guess one.
        # Also try to import tools if available? No, stick to client methods.
        
        # Let's try fetching ~Yoshua_Bengio1 directly
        author_id = '~Yoshua_Bengio1'
        print(f"Fetching profile for {author_id} directly...")
        
        try:
            profile = client.get_profile(author_id)
            print("Profile Content Keys:", profile.content.keys())
            
            # Check history / relations / publications
            if 'history' in profile.content:
                 hist = profile.content['history']
                 print(f"History items: {len(hist)}")
                 # Check for 'award' in history description or similar
                 for item in hist:
                     # Item structure: {'position': '...', 'institution': {...}, 'start': ...}
                     # Sometimes awards are listed?
                     print(item)
            
            # Check publications for "award" in content?
            # Profile object doesn't have publications list directly in content usually in V2, 
            # we need to query notes authored by them.
            
            print("\nSearching for papers by this author to check for awards...")
            # Awards are usually notes with invitation like "Venue/-/Paper/Award" or a field in the paper note?
            # Or "Best Paper" decision?
            
            notes = client.get_notes(content={'authorids': author_id}, limit=5)
            print(f"Found {len(notes)} notes.")
            for n in notes:
                # check content for award fields
                print(f"Note {n.id} content keys: {n.content.keys()}")
                if 'award' in n.content:
                    print(f"AWARD FOUND: {n.content['award']}")
                if 'venue' in n.content:
                     print(f"Venue: {n.content['venue']}")

        except Exception as e:
            print(f"Direct profile fetch failed: {e}")

    except Exception as e:
        print(f"Client init failed: {e}")

if __name__ == "__main__":
    main()
