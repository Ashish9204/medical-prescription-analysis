import streamlit as st
import pytesseract
from PIL import Image
from pymongo import MongoClient
from datetime import datetime
import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Tesseract path - needs to be modified for cloud deployment
if os.path.exists('/app/.apt/usr/bin/tesseract'):
    # Path for Streamlit Cloud
    pytesseract.pytesseract.tesseract_cmd = '/app/.apt/usr/bin/tesseract'
else:
    # Local Windows path
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# MongoDB Configuration - use environment variable for cloud deployment
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = "medical_prescriptions"
COLLECTION_NAME = "extracted_texts"

# Mistral API Configuration
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

def get_db_connection():
    """Establish connection to MongoDB"""
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        # Test the connection by pinging the server
        client.admin.command('ping')
        st.success("Database connection successful!")
        return collection
    except Exception as e:
        st.warning(f"Database connection error: {e}. Some features will be limited.")
        return None

def extract_text_from_image(image):
    """Extract text from image using Tesseract OCR"""
    try:
        text = pytesseract.image_to_string(image)
        return text.strip() if text else "No text detected"
    except Exception as e:
        st.error(f"Error extracting text: {e}")
        return None

def save_to_database(extracted_text, collection):
    """Save extracted text to MongoDB"""
    try:
        prescription_data = {
            "extracted_text": extracted_text,
            "upload_date": datetime.now()
        }
        result = collection.insert_one(prescription_data)
        st.write(f"Insert operation result: {result.inserted_id}")  # Debug output
        return result.inserted_id
    except Exception as e:
        st.error(f"Error saving to database: {str(e)}")
        return None

def fetch_stored_prescriptions(collection):
    """Fetch all stored prescriptions from MongoDB"""
    try:
        return list(collection.find().sort("upload_date", -1))
    except Exception as e:
        st.error(f"Error fetching prescriptions: {e}")
        return []

def query_mistral_api(prompt, prescription_data=None):
    """Query the Mistral API with the user's prompt and prescription data"""
    try:
        if not MISTRAL_API_KEY:
            return "Error: Mistral API key not found. Please set it in the .env file."
            
        # Prepare context with prescription data if available
        context = ""
        system_message = ""
        
        if prescription_data:
            context = f"\nPrescription data: {prescription_data}"
            system_message = f"You are a medical assistant that helps analyze prescription data. Answer questions based on the following prescription data:{context}"
        else:
            system_message = "You are a helpful medical assistant that can answer general medical questions. Note that you are not a replacement for professional medical advice."
            
        # Prepare the API request
        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # The endpoint might vary based on Mistral's API documentation
        url = "https://api.mistral.ai/v1/chat/completions"
        
        payload = {
            "model": "mistral-large-latest",  # Use appropriate model name
            "messages": [
                {"role": "system", "content": system_message}, 
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        # Extract the response text based on Mistral API response format
        result = response.json()
        return result["choices"][0]["message"]["content"]
        
    except Exception as e:
        return f"Error querying Mistral API: {str(e)}"

def display_chat_interface(prescription_data=None):
    """Display a chat interface for querying prescription data"""
    # Different title based on whether prescription data is provided
    if prescription_data:
        st.subheader("Chat with your Prescription Data")
    else:
        st.subheader("Direct Medical Chat")
    
    # Initialize chat history in session state if it doesn't exist
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    
    # Display chat history
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.write(message["content"])
    
    # Chat input - different placeholder based on context
    placeholder = "Ask about your prescription..." if prescription_data else "Ask any medical question..."
    user_query = st.chat_input(placeholder)
    
    if user_query:
        # Add user message to chat history
        st.session_state.chat_history.append({"role": "user", "content": user_query})
        
        # Display user message
        with st.chat_message("user"):
            st.write(user_query)
        
        # Get response from Mistral API
        with st.spinner("Thinking..."):
            response = query_mistral_api(user_query, prescription_data)
        
        # Add assistant response to chat history
        st.session_state.chat_history.append({"role": "assistant", "content": response})
        
        # Display assistant response
        with st.chat_message("assistant"):
            st.write(response)
            
    # Add a button to clear chat history
    if st.session_state.chat_history and st.button("Clear Chat History", key="clear_chat_history_button"):
        st.session_state.chat_history = []
        st.rerun()

def main():
    st.title("Medical Prescription Analyzer")
    st.write("Upload a handwritten medical prescription to extract text or chat directly")

    # Sidebar for navigation
    st.sidebar.title("Navigation")
    
    # Initialize page in session state if it doesn't exist
    if "page" not in st.session_state:
        st.session_state.page = "Extract Text"
    
    # Use the sidebar to change the page in session state
    selected_page = st.sidebar.radio("Go to", ["Extract Text", "Chat with Prescription Data", "Direct Chat"])
    if selected_page != st.session_state.page:
        st.session_state.page = selected_page
        st.rerun()
    
    # Get the current page from session state
    page = st.session_state.page
    
    # Initialize database connection only if needed
    collection = None
    if page in ["Extract Text", "Chat with Prescription Data"]:
        collection = get_db_connection()
        # If database connection fails, show a warning but don't block functionality
        if collection is None and page == "Chat with Prescription Data":
            st.warning("Database connection failed. Some features may be limited.")
    
    if page == "Extract Text":
        # File uploader
        uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "png", "jpeg"])
        
        if uploaded_file is not None:
            image = Image.open(uploaded_file)
            st.image(image, caption="Uploaded Prescription", use_column_width=True)
            
            # Extract Text Button
            if st.button("Extract Text"):
                with st.spinner("Processing image..."):
                    extracted_text = extract_text_from_image(image)
                    
                    if extracted_text:
                        st.subheader("Extracted Text")
                        st.text_area("Result", extracted_text, height=300, key="extracted_text_area")
                        
                        # Database operations
                        if collection is not None:
                            col1, col2, col3 = st.columns(3)
                            
                            with col1:
                                if st.button("Submit to Database", key="submit_to_db_button"):
                                    with st.spinner("Saving to database..."):
                                        result_id = save_to_database(extracted_text, collection)
                                        if result_id:
                                            st.success(f"Successfully saved! Document ID: {result_id}")
                                        else:
                                            st.error("Failed to save to database. Check MongoDB status.")
                            
                            with col2:
                                if st.button("View Stored Prescriptions", key="view_prescriptions_button"):
                                    with st.spinner("Fetching prescriptions..."):
                                        prescriptions = fetch_stored_prescriptions(collection)
                                        if prescriptions:
                                            st.subheader("Stored Prescriptions")
                                            for idx, prescription in enumerate(prescriptions):
                                                st.write(f"Prescription {idx + 1} - {prescription['upload_date']}")
                                                st.text_area(f"Text {idx + 1}", 
                                                           prescription['extracted_text'], 
                                                           height=200, 
                                                           key=f"text_{idx}")
                                        else:
                                            st.info("No prescriptions found in database")
                            
                            with col3:
                                if st.button("Chat with this Prescription", key="chat_prescription_button"):
                                    # Store the extracted text in session state for chat
                                    st.session_state.current_prescription = extracted_text
                                    # Set the page to 'Chat with Prescription Data' in session state
                                    st.session_state.page = "Chat with Prescription Data"
                                    # Switch to chat page
                                    st.rerun()
                        else:
                            # Even if database connection fails, still allow chat functionality
                            if st.button("Chat with this Prescription", key="chat_prescription_no_db_button"):
                                # Store the extracted text in session state for chat
                                st.session_state.current_prescription = extracted_text
                                # Set the page to 'Chat with Prescription Data' in session state
                                st.session_state.page = "Chat with Prescription Data"
                                # Switch to chat page
                                st.rerun()
                            
                            st.warning("Database connection failed. You can still chat with the prescription but it won't be saved.")
    
    elif page == "Chat with Prescription Data":
        st.subheader("Chat with Prescription Data")
        
        # Check if there's a current prescription in session state
        has_current_prescription = "current_prescription" in st.session_state and st.session_state.current_prescription
        
        # Initialize prescription data
        prescription_data = ""
        
        # If database is connected, offer database options
        if collection is not None:
            # Get all prescriptions
            prescriptions = fetch_stored_prescriptions(collection)
            
            if prescriptions:
                # Create options for the selectbox
                prescription_options = [f"Prescription {idx + 1} - {prescription['upload_date']}" 
                                       for idx, prescription in enumerate(prescriptions)]
                prescription_options.insert(0, "All Prescriptions")
                
                # Add option to use current prescription if available
                if has_current_prescription:
                    prescription_options.insert(0, "Current Extracted Prescription")
                
                selected_option = st.selectbox("Choose prescription data to query", prescription_options)
                
                # Prepare prescription data based on selection
                if selected_option == "All Prescriptions":
                    prescription_data = "\n\n".join([f"Prescription {idx + 1}:\n{prescription['extracted_text']}" 
                                              for idx, prescription in enumerate(prescriptions)])
                elif selected_option == "Current Extracted Prescription":
                    prescription_data = st.session_state.current_prescription
                else:
                    # Extract index from the option string
                    idx = int(selected_option.split(" ")[1]) - 1
                    prescription_data = prescriptions[idx]["extracted_text"]
            elif has_current_prescription:
                # If no prescriptions in database but we have current prescription
                st.info("Using current extracted prescription data.")
                prescription_data = st.session_state.current_prescription
            else:
                st.info("No prescriptions found in database. Please extract text first or use Direct Chat.")
                return
        elif has_current_prescription:
            # If database is not connected but we have current prescription
            st.info("Using current extracted prescription data.")
            prescription_data = st.session_state.current_prescription
        else:
            st.warning("No prescription data available. Please extract text first or use Direct Chat.")
            return
        
        # Display the selected prescription data
        with st.expander("View Selected Prescription Data"):
            st.text_area("Prescription Data", prescription_data, height=200)
        
        # Display chat interface
        display_chat_interface(prescription_data)
        
    elif page == "Direct Chat":
        st.subheader("Direct Chat with Medical Assistant")
        st.write("Chat directly with the medical assistant without any prescription data.")
        
        # Display chat interface without prescription data
        display_chat_interface()

if __name__ == "__main__":
    # Initialize session state for navigation
    if "current_prescription" not in st.session_state:
        st.session_state.current_prescription = None
    
    main()