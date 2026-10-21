EON Prospect Prioritization + Contact Intelligence
LOCAL SHARED PACKAGE

FILES
-----
1. EON_Prospect_Ranker_DEMO_FAST_CACHED.html
   - Same ranking methodology as the stable version.
   - Runs contact research for eligible uploaded companies, up to 5 concurrently.
   - Remembers successful contact results in that browser's local storage.

2. EON_Prospect_Ranker_ORIGINAL_STABLE.html
   - Original stable/classic website.
   - Included as a backup/reference.

3. eon_contact_research_server_agentic_v1.py
   - Local Contact Intelligence backend.
   - Uses Brave Search + OpenAI.
   - Full Agentic V1 quality rules remain in place.

REQUIREMENTS
------------
- Python 3
- An OpenAI API key
- A Brave Search API key
- Internet connection
- A modern browser

No extra Python packages are required by this backend; it uses Python's standard library.

IMPORTANT
---------
API keys are NOT included in this ZIP. Each user should use their own keys.
Never paste API keys into the HTML or Python source file.

MAC / LINUX STARTUP
-------------------
1. Unzip this folder.

2. Open Terminal and move into the unzipped folder. Example:
   cd ~/Downloads/EON_Contact_Intelligence_Shared_Package

3. Set the two API keys in that Terminal window:
   export BRAVE_SEARCH_API_KEY="YOUR_BRAVE_KEY"
   export OPENAI_API_KEY="YOUR_OPENAI_KEY"

4. Start the backend:
   python3 eon_contact_research_server_agentic_v1.py

5. Leave that Terminal window open.
   You should see:
   EON Contact Research API AGENTIC V1 listening on http://localhost:8787

6. Open EON_Prospect_Ranker_DEMO_FAST_CACHED.html in the browser.

7. Upload the EON CSV and use the site normally.

WINDOWS POWERSHELL STARTUP
--------------------------
1. Unzip this folder.

2. Open PowerShell in the unzipped folder.

3. Set the two API keys:
   $env:BRAVE_SEARCH_API_KEY="YOUR_BRAVE_KEY"
   $env:OPENAI_API_KEY="YOUR_OPENAI_KEY"

4. Start the backend:
   python eon_contact_research_server_agentic_v1.py

5. Leave PowerShell open, then open the HTML website in the browser.

NOTES
-----
- The backend runs locally at http://localhost:8787.
- Closing the Terminal/PowerShell window stops NEW Contact Intelligence research.
- Ranking itself runs in the browser.
- Cached contacts in the FAST+CACHED website are stored per browser/computer and do not transfer automatically between users.
- The first time another user researches a company, their machine will perform the live research and then cache the successful result locally.
