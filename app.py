import streamlit as st
import requests
import os
import base64
import json
import time
from io import BytesIO
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
import fitz  # PyMuPDF
import pycountry  # for country list
from groq import Groq
import tempfile
# Add at the top of your imports section
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
# Suppress only the specific InsecureRequestWarning when needed
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
# Load environment variables
load_dotenv()

# API Keys - set these in your .env file or in Hugging Face Secrets
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Using Groq as free LLM API

# Initialize Groq client (free alternative to OpenAI)
groq_client = Groq(api_key=GROQ_API_KEY)

# Constants
COUNTRIES = sorted([country.name for country in pycountry.countries])

# Set up sessions state for persistence
if 'search_results' not in st.session_state:
    st.session_state.search_results = []
if 'selected_pdf' not in st.session_state:
    st.session_state.selected_pdf = None
if 'form_fields' not in st.session_state:
    st.session_state.form_fields = []
if 'pdf_bytes' not in st.session_state:
    st.session_state.pdf_bytes = None
if 'search_history' not in st.session_state:
    st.session_state.search_history = []
if 'form_selected' not in st.session_state:
    st.session_state.form_selected = False
if 'selected_form_url' not in st.session_state:
    st.session_state.selected_form_url = ""
if 'selected_form_index' not in st.session_state:
    st.session_state.selected_form_index = -1

# Search using SERPER API
def serper_search(query, country_code="pk"):
    url = "https://google.serper.dev/search"
    
    # Always use Pakistan-specific domains
    country_domain = "site:.gov.pk OR site:.fbr.gov.pk"
    
    # Build the search query
    search_query = f"{query} tax form {country_domain} filetype:pdf"
    
    data = {
        "q": search_query,
        "gl": "pk",  # Force Pakistan search
        "hl": "en"
    }
    
    try:
        # Check if API key is available
        if not SERPER_API_KEY:
            # Fall back to a free method if no API key
            st.warning("SERPER API key not found. Falling back to limited search.")
            return fallback_search(query, "pk")
            
        headers = {"X-API-KEY": SERPER_API_KEY}
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 200:
            results = response.json().get("organic", [])
            # Store in session state
            st.session_state.search_results = results
            return results
        else:
            st.error(f"Search API error: {response.status_code}")
            return []
    except Exception as e:
        st.error(f"Search failed: {str(e)}")
        return []
# Add this function to handle Pakistan-specific government website errors
def handle_pk_gov_errors(error_type, url=""):
    """Provides Pakistan-specific error handling and suggestions"""
    
    if "SSL" in str(error_type):
        st.error("Pakistan government websites often have SSL certificate issues.")
        st.markdown("""
        ### How to access these forms:
        
        1. **Direct FBR Access**: Visit [FBR's website](https://fbr.gov.pk/downloads) and navigate to the forms section
        
        2. **Try these alternative official sources**:
           - [FBR E-Services Portal](https://e.fbr.gov.pk/)
           - [IRIS Portal](https://iris.fbr.gov.pk/)
           - [Tax Facilitation Center](https://tfc.fbr.gov.pk/)
        
        3. **Common Pakistan Tax Forms**:
           - [Income Tax Return for Salaried Individuals](https://download1.fbr.gov.pk/Docs/20221311411725368IncomeTaxReturnFormforSalariedIndividuals.pdf)
           - [Sales Tax Return Form](https://download1.fbr.gov.pk/Docs/202198174726316STGO12of2021-AnnexSTR.pdf)
           - [Wealth Statement Form](https://download1.fbr.gov.pk/Docs/201212129391942FormWealthStatement.pdf)
        """)
        
    elif "timeout" in str(error_type).lower():
        st.error("Pakistan government servers may be experiencing high load or connectivity issues.")
        st.info("Try again during off-peak hours (early morning or late evening Pakistan time).")
        
    elif "connection" in str(error_type).lower():
        st.error("Connection issues with Pakistan government servers.")
        st.info("This is a common issue that could be due to server maintenance or regional access restrictions.")
        
    else:
        st.error(f"Error accessing Pakistan government resource: {error_type}")
        
    # Always provide the direct URL for manual access
    if url:
        st.markdown(f"""
        **Try opening the link directly in your browser**:
        <a href="{url}" target="_blank">
        <button style="background-color:#4CAF50;color:white;padding:10px 24px;border:none;
        border-radius:4px;cursor:pointer;">Open Link in Browser</button>
        </a>
        """, unsafe_allow_html=True)
        
    return None
# Add this function to handle FBR-specific PDF fetching
# Replace your fetch_fbr_pdf function with this improved version
def fetch_fbr_pdf(url):
    """Special handler for FBR website PDFs which often have SSL issues"""
    try:
        st.info("Using specialized FBR website handler...")
        
        # Create a custom session with improved SSL handling
        session = requests.Session()
        
        # Add various retry and timeout strategies
        retry = requests.packages.urllib3.util.retry.Retry(
            total=5,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = requests.adapters.HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        # Try multiple approaches
        approaches = [
            # Approach 1: Modified URL to use HTTP instead of HTTPS
            {"url": url.replace("https://", "http://"), "verify": False, "timeout": 30},
            # Approach 2: Original URL with no verification and custom headers
            {"url": url, "verify": False, "timeout": 30, 
             "headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/89.0"}},
            # Approach 3: Try alternate domain pattern (sometimes used by FBR)
            {"url": url.replace("download1.fbr.gov.pk", "download.fbr.gov.pk"), "verify": False, "timeout": 30},
        ]
        
        for i, approach in enumerate(approaches):
            try:
                headers = approach.get("headers", {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36"
                })
                
                st.write(f"Trying approach {i+1} with URL: {approach['url']}")
                r = session.get(
                    approach["url"], 
                    headers=headers,
                    verify=approach["verify"],
                    timeout=approach["timeout"]
                )
                
                if r.status_code == 200:
                    content_type = r.headers.get('Content-Type', '')
                    st.write(f"Success with approach {i+1}! Content-Type: {content_type}")
                    
                    if 'application/pdf' in content_type or approach["url"].lower().endswith('.pdf'):
                        return BytesIO(r.content)
                    else:
                        st.warning(f"Response is not a PDF! Content-Type: {content_type}")
            except Exception as e:
                st.write(f"Approach {i+1} failed: {str(e)}")
                continue
                
        # If all approaches fail, provide alternate instructions
        st.error("All automated attempts to fetch the PDF failed.")
        st.markdown("""
        ### Alternative download methods:
        
        1. **Try downloading directly**: 
           - Open the link in your browser: [FBR Download Page](https://fbr.gov.pk/downloads)
           - Search for your form and download it manually
        
        2. **Visit an FBR facilitation center** in your city
        
        3. **Common direct links** (may work in browser):
           - [Income Tax Return Form](https://download1.fbr.gov.pk/Docs/20221311411725368IncomeTaxReturnFormforSalariedIndividuals.pdf)
           - [Sales Tax Registration](https://download1.fbr.gov.pk/Docs/20198117833751FormSTR-1.pdf)
        """, unsafe_allow_html=True)
        
        return None
    except Exception as e:
        st.error(f"FBR PDF fetch failed: {str(e)}")
        return None
# Fallback search method (limited, but free)
# Improved fallback search method
def fallback_search(query, country_code=""):
    try:
        # Format country code for search
        country_name = next((country.name for country in pycountry.countries if country.alpha_2.lower() == country_code.lower()), "")
        
        # For Pakistan, add special handling
        if country_code.lower() == "pk" or country_name.lower() == "pakistan":
            st.info("Using Pakistan-specific search method...")
            
            # List of common Pakistan tax form sources
            pk_sources = [
                {"name": "FBR Main Website", "url": "https://fbr.gov.pk"},
                {"name": "FBR Forms", "url": "https://download1.fbr.gov.pk/Docs/"},
                {"name": "Income Tax Ordinance", "url": "https://fbr.gov.pk/Income-Tax-Ordinances/132145/20210714192563217"}
            ]
            
            # Show users direct links to common Pakistan tax resources
            st.markdown("### Common Pakistan Tax Resources:")
            for source in pk_sources:
                st.markdown(f"- [{source['name']}]({source['url']})")
                
            # Try to construct a direct URL for common form types
            if "income tax" in query.lower() or "itr" in query.lower():
                st.info("Looking for Income Tax Return forms...")
                direct_suggestions = [
                    {"title": "Income Tax Return for Salaried Individuals", 
                     "link": "https://download1.fbr.gov.pk/Docs/20221311411725368IncomeTaxReturnFormforSalariedIndividuals.pdf"},
                    {"title": "Income Tax Return for Association of Persons (AOP)", 
                     "link": "https://download1.fbr.gov.pk/Docs/20198117833692FormITR-AOP.pdf"},
                    {"title": "Income Tax Return for Companies", 
                     "link": "https://download1.fbr.gov.pk/Docs/2021815168381733CompanyReturn2021.pdf"}
                ]
                return direct_suggestions
                
            elif "sales tax" in query.lower():
                st.info("Looking for Sales Tax Return forms...")
                direct_suggestions = [
                    {"title": "Sales Tax Return Form", 
                     "link": "https://download1.fbr.gov.pk/Docs/202198174726316STGO12of2021-AnnexSTR.pdf"},
                    {"title": "Sales Tax Registration Form", 
                     "link": "https://download1.fbr.gov.pk/Docs/20198117833751FormSTR-1.pdf"}
                ]
                return direct_suggestions
        
        # Use a different free API or direct scraping approach
        search_query = quote_plus(f"{query} {country_name} tax form pdf")
        url = f"https://ddg-api.herokuapp.com/search?query={search_query}&limit=5"
        
        response = requests.get(url)
        if response.status_code == 200:
            results = response.json()
            # Convert to a format similar to Serper
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "title": result.get("title", ""),
                    "link": result.get("link", ""),
                    "snippet": result.get("snippet", "")
                })
            return formatted_results
        return []
    except Exception as e:
        st.error(f"Fallback search failed: {str(e)}")
        return []

# Use LLM to extract relevant information from search results
def analyze_search_results(results, query, country):
    if not GROQ_API_KEY:
        return results  # Return unprocessed results if no LLM available
    
    try:
        # Prepare results for LLM analysis
        results_text = json.dumps(results[:5], indent=2)
        
        prompt = f"""
        I'm looking for tax forms for {country} related to "{query}".
        
        Here are search results:
        {results_text}
        
        Please analyze these results and tell me:
        1. Which result is most likely the official tax form I need?
        2. Is this result from an official government source?
        3. What specific form number or name should I be looking for?
        4. Any additional forms I might need based on this search intent?
        
        Format your response as JSON with the following keys:
        {{
            "best_result_index": 0-4 (index of the best result, or -1 if none are good),
            "is_official": true/false,
            "form_name": "string",
            "form_description": "string",
            "additional_forms": ["form1", "form2"]
        }}
        """
        
        # Call Groq API with mixed model approach (prefer cheaper model)
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",  # Free/cheaper model
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=800
        )
        
        try:
            # Parse the response as JSON
            analysis = json.loads(completion.choices[0].message.content)
            return results, analysis
        except json.JSONDecodeError:
            # If parsing fails, return the original results
            return results, None
            
    except Exception as e:
        st.error(f"LLM analysis failed: {str(e)}")
        return results, None

# Try to download PDF
# Update the fetch_pdf function with improved error handling
def fetch_pdf(url):
    try:
        # First determine if this is an FBR URL - use specialized handler
        if any(domain in url.lower() for domain in ["fbr.gov.pk", "download1.fbr.gov.pk", "download.fbr.gov.pk"]):
            st.info("Detected FBR website URL - using specialized handler")
            fbr_result = fetch_fbr_pdf(url)
            if fbr_result:
                return fbr_result
            # If the specialized handler failed, don't attempt with standard handler
            else:
                # Show Pakistan-specific fallback options
                handle_pk_gov_errors("SSL Certificate Error", url)
                return None
                
        # For non-FBR URLs, use the standard approach
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        st.write(f"Attempting to download PDF from: {url}")
        
        # Create a session with retry capabilities
        session = requests.Session()
        retry_strategy = requests.packages.urllib3.util.retry.Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        session.mount('https://', requests.adapters.HTTPAdapter(max_retries=retry_strategy))
        session.mount('http://', requests.adapters.HTTPAdapter(max_retries=retry_strategy))
        
        try:
            # First try with verification enabled (safer)
            r = session.get(url, headers=headers, timeout=20)
        except requests.exceptions.SSLError:
            st.warning("SSL certificate validation failed. Trying alternate method...")
            # If SSL verification fails, try without verification
            r = session.get(url, headers=headers, timeout=20, verify=False)
            
        st.write(f"Response status code: {r.status_code}")
        st.write(f"Content-Type: {r.headers.get('Content-Type', 'Not specified')}")
        
        if r.status_code == 200:
            if 'application/pdf' in r.headers.get('Content-Type', '') or url.lower().endswith('.pdf'):
                st.success("Successfully retrieved PDF!")
                return BytesIO(r.content)
            else:
                st.info("URL doesn't point directly to a PDF. Searching for PDF links on the page...")
                # Try to find PDF links if this is an HTML page
                pdf_url = find_pdf_in_html_page(url, r.text)
                if pdf_url:
                    st.info(f"Found PDF link: {pdf_url}")
                    return fetch_pdf(pdf_url)
                else:
                    st.warning("No PDF links found on the page")
        else:
            st.error(f"Failed to retrieve URL: {r.status_code}")
            
        # Provide a better error message for the user
        if "fbr.gov.pk" in url.lower():
            handle_pk_gov_errors("Connection Error", url)
        else:
            st.error("Unable to retrieve the PDF. This could be due to:")
            st.markdown("""
            1. The server might be temporarily down
            2. The PDF might require authentication
            3. The URL might be incorrect or outdated
            """)
            
        return None
    except Exception as e:
        st.error(f"Error fetching PDF: {str(e)}")
        
        # Add additional handling for common FBR website issues
        if "fbr.gov.pk" in url:
            handle_pk_gov_errors(str(e), url)
        return None

# Scrape .pdf links from HTML page
def find_pdf_in_html_page(url, html_content=None):
    try:
        if not html_content:
            r = requests.get(url, timeout=10)
            html_content = r.text
            
        soup = BeautifulSoup(html_content, "html.parser")
        pdf_links = []
        
        # Look for PDF links
        st.write("Scanning page for PDF links...")
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.lower().endswith('.pdf'):
                full_url = href if href.startswith("http") else urljoin(url, href)
                pdf_links.append((full_url, link.text.strip()))
                st.write(f"Found PDF link: {full_url} - {link.text.strip()}")
        
        st.write(f"Total PDF links found: {len(pdf_links)}")
        
        # First, look for links with "tax", "form", or "return" in them
        for link_url, link_text in pdf_links:
            combined_text = (link_url + " " + link_text).lower()
            if any(keyword in combined_text for keyword in ["tax", "form", "return", "income"]):
                st.success(f"Selected most relevant PDF: {link_url}")
                return link_url
                
        # If no specific tax links, return the first PDF link
        if pdf_links:
            st.info(f"No tax-specific PDFs found. Using first PDF: {pdf_links[0][0]}")
            return pdf_links[0][0]
        
        st.warning("No PDF links found on the page")
        return None
    except Exception as e:
        st.error(f"Error finding PDF links: {str(e)}")
        return None

# Display PDF safely with error handling
def display_pdf(file_bytesio):
    try:
        file_bytesio.seek(0)
        base64_pdf = base64.b64encode(file_bytesio.read()).decode('utf-8')
        pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800" type="application/pdf"></iframe>'
        st.markdown(pdf_display, unsafe_allow_html=True)
        st.success("PDF loaded successfully!")
        
        # Add a direct download option for better user experience
        file_bytesio.seek(0)
    except Exception as e:
        st.error(f"Error displaying PDF: {str(e)}")
        st.info("If the PDF isn't displaying, you can try using the direct link.")


# Extract interactive fields from PDF
def extract_form_fields(file_bytesio):
    try:
        file_bytesio.seek(0)
        doc = fitz.open(stream=file_bytesio, filetype="pdf")
        
        fields = []
        widget_types = {
            fitz.PDF_WIDGET_TYPE_TEXT: "Text Field",
            fitz.PDF_WIDGET_TYPE_CHECKBOX: "Checkbox",
            fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "Radio Button",
            fitz.PDF_WIDGET_TYPE_COMBOBOX: "Dropdown",
            fitz.PDF_WIDGET_TYPE_LISTBOX: "List Box"
        }
        
        for page_num, page in enumerate(doc):
            widgets = page.widgets()
            for widget in widgets:
                field_type = widget_types.get(widget.field_type, "Unknown")
                field_info = {
                    "name": widget.field_name or f"Field_{page_num}_{len(fields)}",
                    "type": field_type,
                    "value": widget.field_value,
                    "options": widget.choice_values if hasattr(widget, "choice_values") else None,
                    "page": page_num + 1
                }
                fields.append(field_info)
        
        return fields
    except Exception as e:
        st.error(f"Error extracting form fields: {str(e)}")
        return []

# Use LLM to explain form fields
def explain_form_fields(fields, country, form_name):
    if not GROQ_API_KEY or not fields:
        return {}
        
    try:
        fields_json = json.dumps(fields, indent=2)
        
        prompt = f"""
        These are form fields from a tax form ({form_name}) from {country}:
        {fields_json}
        
        Please analyze these fields and:
        1. Group them into logical sections (personal info, income, deductions, etc.)
        2. Explain any technical tax terms in simple language
        3. Identify which fields are mandatory vs. optional if possible
        
        Format your response as JSON with the following structure:
        {{
            "sections": [
                {{
                    "name": "section name",
                    "fields": ["field1", "field2"],
                    "explanation": "explanation of this section"
                }}
            ],
            "key_terms": {{
                "term1": "simple explanation",
                "term2": "simple explanation"
            }},
            "mandatory_fields": ["field1", "field2"]
        }}
        """
        
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000
        )
        
        try:
            explanation = json.loads(completion.choices[0].message.content)
            return explanation
        except json.JSONDecodeError:
            return {}
            
    except Exception as e:
        st.error(f"Error explaining form fields: {str(e)}")
        return {}

# Fill PDF form with user data
def fill_pdf_form(file_bytesio, field_values):
    try:
        file_bytesio.seek(0)
        doc = fitz.open(stream=file_bytesio, filetype="pdf")
        
        # Fill in the form fields
        for page in doc:
            widgets = page.widgets()
            for widget in widgets:
                field_name = widget.field_name
                if field_name in field_values:
                    widget.field_value = field_values[field_name]
                    widget.update()
        
        # Save to a temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        doc.save(temp_file.name)
        doc.close()
        
        # Read the saved file back
        with open(temp_file.name, "rb") as f:
            filled_pdf = BytesIO(f.read())
        
        # Clean up
        os.unlink(temp_file.name)
        
        return filled_pdf
    except Exception as e:
        st.error(f"Error filling form: {str(e)}")
        return None
# Add this code to your Streamlit app's Tab 2 (Search Forms) section
# Place it right after the search results display, before displaying the PDF

# Manual upload option for when automatic fetching fails
st.markdown("### 🔄 Can't fetch the form automatically?")
col1, col2 = st.columns([1, 2])

with col1:
    manual_upload = st.file_uploader("Upload the PDF form directly:", type=["pdf"])
    
    if manual_upload:
        try:
            # Process the uploaded PDF
            pdf_bytes = BytesIO(manual_upload.getvalue())
            st.session_state.pdf_bytes = pdf_bytes
            st.session_state.form_fields = extract_form_fields(pdf_bytes)
            st.success(f"Successfully loaded {manual_upload.name}!")
            
            # Add to history
            add_to_history("Pakistan", "Manually uploaded form", None)
        except Exception as e:
            st.error(f"Error processing uploaded PDF: {str(e)}")

with col2:
    st.info("""
    **Experiencing issues with automatic form downloads?**
    
    Many Pakistani government websites have technical issues that can prevent automatic downloads.
    
    If you already have the tax form saved on your computer, you can upload it directly.
    
    You can also try downloading forms directly from:
    - [FBR Downloads Page](https://fbr.gov.pk/downloads)
    - [IRIS Portal](https://iris.fbr.gov.pk/)
    """)
# Add to search history
def add_to_history(country, query, pdf_url=None):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.search_history.append({
        "timestamp": timestamp,
        "country": country,
        "query": query,
        "pdf_url": pdf_url
    })
    # Keep only the last 10 searches
    if len(st.session_state.search_history) > 10:
        st.session_state.search_history = st.session_state.search_history[-10:]

# Get country code from name
def get_country_code(country_name):
    try:
        country = pycountry.countries.get(name=country_name)
        return country.alpha_2 if country else ""
    except:
        return ""

# Function to suggest other forms
def suggest_other_forms():
    """Suggest other forms from search results if current form isn't fillable"""
    if ('search_results' in st.session_state and 
        st.session_state.search_results and 
        'selected_pdf' in st.session_state):
        
        selected_idx = st.session_state.selected_pdf
        st.markdown("### 🔎 Try These Other Forms")
        
        # Display up to 5 alternative forms
        other_forms = [r for i, r in enumerate(st.session_state.search_results[:5]) 
                      if i != selected_idx]
        
        for idx, result in enumerate(other_forms):
            title = result.get('title', 'Untitled Form')
            link = result.get('link', '')
            
            st.markdown(f"**{idx+1}. {title}**")
            if st.button(f"Try Form #{idx+1}", key=f"try_form_{idx}"):
                with st.spinner(f"Fetching alternative form #{idx+1}..."):
                    pdf_bytes = fetch_pdf(link)
                    if pdf_bytes:
                        st.session_state.pdf_bytes = pdf_bytes
                        st.session_state.selected_pdf = idx
                        st.session_state.form_fields = extract_form_fields(pdf_bytes)

# Add this new function
def tax_agent_response(user_query, tax_form_type=None, form_fields=None):
    """Generate an agent-like response to user tax questions using LLM"""
    if not GROQ_API_KEY:
        return "I need an LLM API key to provide detailed assistance. Please upload a PDF or search for forms directly."
    
    try:
        # Create context from available information
        context = f"The user is asking about Pakistani tax: '{user_query}'\n"
        
        if tax_form_type:
            context += f"They previously selected tax form type: {tax_form_type}\n"
            
        if form_fields and len(form_fields) > 0:
            fields_sample = ", ".join([f["name"] for f in form_fields[:5]])
            context += f"They are looking at a form with fields including: {fields_sample}\n"
        
        # Pakistan-specific tax information to help ground the response
        context += """
        Pakistan tax information:
        - FBR (Federal Board of Revenue) is the main tax authority
        - Common tax forms include income tax returns, sales tax returns, and withholding tax statements
        - The tax year in Pakistan typically runs from July to June
        - NTN (National Tax Number) is required for filing taxes in Pakistan
        """
        
        prompt = f"""
        {context}
        
        As a LifePilot Tax Agent specialized in Pakistani taxation, provide a helpful response to their query.
        If they are asking about which tax form they need, explain the options and help them decide.
        If they are asking about how to fill a specific field, provide guidance.
        If they need information about tax filing deadlines or procedures, provide accurate information.
        
        Your response should be:
        1. Conversational and helpful
        2. Specific to Pakistan's tax system
        3. Brief but informative
        """
        
        # Call Groq API 
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",  # Or "mixtral-8x7b-32768" if available
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800
        )
        
        return completion.choices[0].message.content
            
    except Exception as e:
        return f"I encountered an error while processing your question: {str(e)}"
# Add this function to recommend tax form types
def recommend_tax_form_type(user_query):
    """Recommend appropriate tax form type based on user's situation"""
    if not GROQ_API_KEY:
        return ["Income Tax Return", "Sales Tax Return", "Withholding Tax Statement"]
    
    try:
        prompt = f"""
        The user is asking about Pakistani taxes: "{user_query}"
        
        Based on their query, which of these Pakistani tax form types would be most relevant?
        - Income Tax Return
        - Sales Tax Return
        - Withholding Tax Statement
        - Property Tax
        - Customs Duty
        - Advance Tax
        - Wealth Statement
        
        Return only the names of the top 3 most relevant form types as a JSON array:
        ["Form Type 1", "Form Type 2", "Form Type 3"]
        """
        
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=100
        )
        
        try:
            # Parse the response as JSON
            return json.loads(completion.choices[0].message.content)
        except json.JSONDecodeError:
            # Fallback to default options
            return ["Income Tax Return", "Sales Tax Return", "Withholding Tax Statement"]
            
    except Exception as e:
        return ["Income Tax Return", "Sales Tax Return", "Withholding Tax Statement"]
# Main Streamlit app
def main():
    st.set_page_config(
        page_title="LifePilot - Pakistan Tax Form Finder", 
        page_icon="📋",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Sidebar
    with st.sidebar:
        st.title("📋LifePilot")
        st.caption("Pakistan Tax Assistant")
        
        st.subheader("📊 History")
        if st.session_state.search_history:
            for idx, item in enumerate(reversed(st.session_state.search_history)):
                with st.expander(f"{item['query']}"):
                    st.write(f"📅 {item['timestamp']}")
                    if item['pdf_url']:
                        st.write(f"[Open PDF]({item['pdf_url']})")
        else:
            st.info("Your search history will appear here👉")
        
        st.divider()
        st.markdown("📋LifePilot| Made with Streamlit")
        
    # Main content area
    st.title("Pakistan Tax Form Finder")
    st.markdown("Search, preview, and get assistance with official Pakistani tax forms.")
    
    # Two main tabs: Search Forms and Upload Forms
    tab1, tab2, tab3 = st.tabs(["🤖 Tax Assistant", "🔍 Search Forms", "📤 Upload Form"])

    # Tab 1: Tax Assistant
    with tab1:
        st.header("Pakistan Tax Assistant")
        st.markdown("Ask any questions about Pakistani taxes or which forms you need.")
        
        # User query input
        user_query = st.text_input("Ask your tax question:", placeholder="Which tax form do I need as a salaried employee?")
        
        # Current form context
        current_form_type = None
        if 'form_fields' in st.session_state and st.session_state.form_fields:
            current_form_type = "Tax Form with fillable fields"
        
        # Process query when submitted
        if user_query:
            with st.spinner("Processing your question..."):
                agent_response = tax_agent_response(
                    user_query, 
                    tax_form_type=current_form_type,
                    form_fields=st.session_state.form_fields if 'form_fields' in st.session_state else None
                )
                
                st.markdown("### Response:")
                st.markdown(agent_response)
                
                # Initialize recommended_types to empty list by default
                recommended_types = []
                
                # Recommend form types if needed
                if "which form" in user_query.lower() or "what form" in user_query.lower() or "do i need" in user_query.lower():
                    st.markdown("### Recommended Form Types:")
                    recommended_types = recommend_tax_form_type(user_query)
                    
                    # Auto-fetch the first recommended form without requiring a button click
                    if recommended_types:
                        form_type = recommended_types[0]
                        with st.spinner(f"Automatically fetching {form_type} forms..."):
                            results = serper_search(form_type, "pk")
                            if results:
                                st.session_state.search_results = results
                                st.success(f"Found {len(results)} {form_type} forms")
                                
                                # Display first result and fetch PDF automatically
                                if results[0].get('link', ''):
                                    with st.spinner("Fetching the most relevant form..."):
                                        pdf_bytes = fetch_pdf(results[0].get('link', ''))
                                        if pdf_bytes:
                                            st.session_state.pdf_bytes = pdf_bytes
                                            st.session_state.form_fields = extract_form_fields(pdf_bytes)
                                            add_to_history("Pakistan", form_type, results[0].get('link', ''))
                                            st.success("Form fetched successfully!")
                                            
                                            # Show form preview immediately
                                            st.markdown("### 📄 Form Preview")
                                            display_pdf(pdf_bytes)
                                            
                                            # If form has fields, show them
                                            if st.session_state.form_fields:
                                                st.markdown("### 📝 Form Fields")
                                                
                                                # Get field explanations if LLM is available
                                                field_explanations = {}
                                                if GROQ_API_KEY:
                                                    with st.spinner("Analyzing form fields..."):
                                                        explanations = explain_form_fields(
                                                            st.session_state.form_fields, 
                                                            "Pakistan", 
                                                            f"{form_type} form"
                                                        )
                                                        if explanations:
                                                            field_explanations = explanations
                                                
                                                # Display fields with explanations if available
                                                if field_explanations and "sections" in field_explanations:
                                                    for section in field_explanations["sections"]:
                                                        with st.expander(f"📑 {section['name']}"):
                                                            st.write(section["explanation"])
                                                            for field_name in section["fields"]:
                                                                matching_fields = [f for f in st.session_state.form_fields 
                                                                                if f["name"] == field_name]
                                                                if matching_fields:
                                                                    field = matching_fields[0]
                                                                    st.write(f"**{field['name']}** ({field['type']})")
                                                else:
                                                    # Simple field display without explanations
                                                    for field in st.session_state.form_fields:
                                                        st.write(f"**{field['name']}** ({field['type']})")
                                        else:
                                            st.error("Unable to fetch this form automatically. Please try another search.")
            
            # Only show buttons for all recommended types if we have any
            if recommended_types:
                for idx, form_type in enumerate(recommended_types):
                    if st.button(f"Find {form_type} Forms", key=f"find_{idx}"):
                        # Set up search for this form type
                        with st.spinner(f"Searching for {form_type} forms..."):
                            results = serper_search(form_type, "pk")
                            if results:
                                st.session_state.search_results = results
                                st.success(f"Found {len(results)} {form_type} forms")
                                
                                # Display first result
                                if results[0].get('link', ''):
                                    with st.spinner("Fetching the most relevant form..."):
                                        pdf_bytes = fetch_pdf(results[0].get('link', ''))
                                        if pdf_bytes:
                                            st.session_state.pdf_bytes = pdf_bytes
                                            st.session_state.form_fields = extract_form_fields(pdf_bytes)
                                            add_to_history("Pakistan", form_type, results[0].get('link', ''))
                                            st.success("Form fetched successfully!")
                                            
                                            # Show form preview immediately
                                            st.markdown("### 📄 Form Preview")
                                            display_pdf(pdf_bytes)
                                        else:
                                            st.error("Unable to fetch this form. Please try another search.")
                
                # Still show buttons for all recommended types
                for idx, form_type in enumerate(recommended_types):
                    if st.button(f"Find {form_type} Forms", key=f"find_{idx}"):
                        # Set up search for this form type
                        with st.spinner(f"Searching for {form_type} forms..."):
                            results = serper_search(form_type, "pk")
                            if results:
                                st.session_state.search_results = results
                                st.success(f"Found {len(results)} {form_type} forms")
                                
                                # Display first result
                                if results[0].get('link', ''):
                                    with st.spinner("Fetching the most relevant form..."):
                                        pdf_bytes = fetch_pdf(results[0].get('link', ''))
                                        if pdf_bytes:
                                            st.session_state.pdf_bytes = pdf_bytes
                                            st.session_state.form_fields = extract_form_fields(pdf_bytes)
                                            add_to_history("Pakistan", form_type, results[0].get('link', ''))
                                            st.success("Form fetched successfully!")
                                            
                                            # Show form preview immediately
                                            st.markdown("### 📄 Form Preview")
                                            display_pdf(pdf_bytes)
                                        else:
                                            st.error("Unable to fetch this form. Please try another search.")
    
    # Tab 2: Search Forms (modified version of original tab1)
    with tab2:
        # Set Pakistan as default country
        country = "Pakistan"
        st.info("🇵🇰 This application is focused on Pakistani tax forms.")
        
        # Form type selection
        form_type = st.selectbox(
            "📝 What tax form are you looking for?",
            ["Income Tax Return", "Sales Tax Return", "Withholding Tax Statement", 
            "Property Tax", "Customs Duty", "Advance Tax", "Wealth Statement"]
        )
        
        # Additional form details for search refinement
        custom_query = st.text_input(
            "✏️ Specific form or additional details:", 
            placeholder="e.g., Salaried individuals, business income, etc."
        )
        
        # Build the search query
        search_query = custom_query if custom_query else form_type
        
        # Search button
        search_button = st.button("🔍 Search for Pakistani Tax Forms", use_container_width=True)
    
        # Only show search results when search button is clicked
        if search_button:
            with st.spinner("Searching for Pakistani tax forms..."):
                # Perform search
                results = serper_search(search_query, "pk")
                
                if results:
                    # Try to analyze results with LLM if available
                    if GROQ_API_KEY:
                        results, analysis = analyze_search_results(results, search_query, "Pakistan")
                        
                        # Show LLM analysis if available
                        if analysis and isinstance(analysis, dict):
                            best_idx = analysis.get("best_result_index", -1)
                            if best_idx >= 0 and best_idx < len(results):
                                st.success(f"✅ Found: {analysis.get('form_name', 'Tax Form')}")
                                st.info(analysis.get('form_description', ''))
                                
                                # If additional forms are suggested
                                additional = analysis.get('additional_forms', [])
                                if additional:
                                    st.markdown("**You might also need:**")
                                    for form in additional:
                                        st.markdown(f"- {form}")
                    
                    # Display results in a cleaner format
                    st.markdown("### 📋 Found Forms")
                    
                    for idx, result in enumerate(results[:5]):
                        title = result.get('title', 'Untitled Form')
                        link = result.get('link', '')
                        snippet = result.get('snippet', '')
                        
                        with st.container():
                            st.subheader(f"{idx+1}. {title}")
                            st.write(snippet)
                            
                            # Get button and Download PDF button side by side
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                # Replace Select Form button with Get Form button
                                pdf_bytes = fetch_pdf(link)
                                if pdf_bytes:
                                    st.session_state.pdf_bytes = pdf_bytes
                                    st.session_state.form_fields = extract_form_fields(pdf_bytes)
                                    add_to_history("Pakistan", search_query, link)
                                    st.success("Form fetched successfully!")
                                else:
                                    st.error("Unable to fetch this form. Please try another.")        
                            
                            with col2:
                                # Direct link to open in new tab
                                st.markdown(
                                    f"""<a href="{link}" target="_blank">
                                            <button style="background-color:#4CAF50;color:white;padding:6px 12px;
                                                        border:none;border-radius:4px;cursor:pointer;width:100%;">
                                                👁️ View Original
                                            </button>
                                    </a>""",
                                    unsafe_allow_html=True
                                )
                            
                            st.divider()
                else:
                    st.warning("No results found. Try different search terms.")
        
        # Display the PDF directly if it exists in session state
        if 'pdf_bytes' in st.session_state and st.session_state.pdf_bytes:
            st.markdown("### 📄 Form Preview")
            display_pdf(st.session_state.pdf_bytes)
            
            # If form has fields, show them
            if 'form_fields' in st.session_state and st.session_state.form_fields:
                st.markdown("### 📝 Form Fields")
                
                # Get field explanations if LLM is available
                field_explanations = {}
                if GROQ_API_KEY:
                    with st.spinner("Analyzing form fields..."):
                        explanations = explain_form_fields(
                            st.session_state.form_fields, 
                            "Pakistan", 
                            f"{form_type} form"
                        )
                        if explanations:
                            field_explanations = explanations
                
                # Display fields with explanations if available
                if field_explanations and "sections" in field_explanations:
                    for section in field_explanations["sections"]:
                        with st.expander(f"📑 {section['name']}"):
                            st.write(section["explanation"])
                            for field_name in section["fields"]:
                                matching_fields = [f for f in st.session_state.form_fields 
                                                if f["name"] == field_name]
                                if matching_fields:
                                    field = matching_fields[0]
                                    st.write(f"**{field['name']}** ({field['type']})")
                else:
                    # Simple field display without explanations
                    for field in st.session_state.form_fields:
                        st.write(f"**{field['name']}** ({field['type']})")
            
                # Option to fill form
                st.markdown("### ✏️ Fill This Form")
                st.info("This feature will help you fill in the form fields.")
                
                if st.button("Start Filling Form"):
                    st.session_state.is_filling = True
            else:
                st.warning("⚠️ This form doesn't have fillable fields. It may be a scanned document or not an interactive form.")
                st.info("You can still view and download the form, but automatic filling isn't available.")
                
                # Option to download the non-fillable form
                st.download_button(
                    label="📥 Download Form",
                    data=st.session_state.pdf_bytes,
                    file_name="pakistan_tax_form.pdf",
                    mime="application/pdf"
                )
                
                # Add a question and answer section for this form
                st.markdown("### ❓ Questions about this form?")
                form_question = st.text_input("Ask a question about this form:", key="form_question_input")
                
                if form_question:
                    with st.spinner("Getting answer..."):
                        form_response = tax_agent_response(form_question, tax_form_type=form_type)
                        st.markdown(form_response)

if __name__ == "__main__":
    main()
