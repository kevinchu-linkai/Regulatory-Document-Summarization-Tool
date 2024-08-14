import streamlit as st
import json
import requests
import tiktoken
from openai import OpenAI
import os
from dotenv import load_dotenv
import bcrypt
import pandas as pd
from fuzzywuzzy import process
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import docx2txt
import PyPDF2
import csv
import io
import re
import concurrent.futures
import httpx
import logging

st.set_page_config(
    page_title="Regulatory Bulletin Assistant",
    page_icon="image/favicon.ico",
    layout="wide"
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv('.env', override=True)

# Initialize tokenizer
tokenizer = tiktoken.encoding_for_model("gpt-3.5-turbo")

# Initialize OpenAI client
http_client = httpx.Client(verify=False)
client = OpenAI(
    base_url='https://opensource-challenger-api.prdlvgpu1.aiaccel.dell.com/v1',
    http_client=http_client,
    api_key=os.environ["CHALLENGER_GENAI_API_KEY"]
)

API_KEY=os.environ["CHALLENGER_GENAI_API_KEY"]

# Constants
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
MODEL = "llama-3-8b-instruct"
MAX_OUTPUT_TOKENS = 4000
MAX_TOKENS = 8192  # Maximum tokens for the model
BUFFER_TOKENS = 50  # Buffer for system message and other overhead

# Initialize session state
if 'conversations' not in st.session_state:
    st.session_state.conversations = {}
if 'current_conversation' not in st.session_state:
    st.session_state.current_conversation = None
if 'guided_questions' not in st.session_state:
    st.session_state.guided_questions = {}
if 'is_admin' not in st.session_state:
    st.session_state.is_admin = False
if 'admin_password_hash' not in st.session_state:
    st.session_state.admin_password_hash = None
if 'context' not in st.session_state:
    st.session_state.context = ""
if 'context_embeddings' not in st.session_state:
    st.session_state.context_embeddings = None
if 'attached_file_content' not in st.session_state:
    st.session_state.attached_file_content = None
if 'file_uploaded' not in st.session_state:
    st.session_state.file_uploaded = False
if 'guided_answers' not in st.session_state:
    st.session_state.guided_answers = {}
if 'prompt_ready' not in st.session_state:
    st.session_state.prompt_ready = False
if 'option_counts' not in st.session_state:
    st.session_state.option_counts = {}
if 'chat_counter' not in st.session_state:
    st.session_state.chat_counter = 0
if 'summary_generated' not in st.session_state:
    st.session_state.summary_generated = False
if 'checkbox_selections' not in st.session_state:
    st.session_state.checkbox_selections = {}

# Initialize embeddings model
@st.cache_resource
def load_embeddings_model():
    return SentenceTransformer('all-MiniLM-L6-v2')

embeddings_model = load_embeddings_model()

# Initialize tokenizer
tokenizer = tiktoken.get_encoding("cl100k_base")

# Load keywords
@st.cache_data
def load_keywords():
    return pd.read_csv('keyword_extraction.csv')

keywords_df = load_keywords()

# Functions
def load_questions():
    try:
        with open('guided_questions.json', 'r') as f:
            st.session_state.guided_questions = json.load(f)
    except FileNotFoundError:
        st.session_state.guided_questions = {
            "Fields": {
                "type": "Check-Box",
                "options": ["EMC", "Safety", "Wireless", "Telecom/PSTN", "Materials", "Energy", "Packaging", "Cybersecurity", "US Federal", "Others"]
            },
            "Impacts": {
                "type": "Check-Box",
                "options": ["Certification / DOC/ Registration", "New/ Revision", "Regulatory Filing", "Design Change", "Component impact", "Cost impact", "Factory inspection", "Label – New/ Revised Packaging Label", "Logistics", "Product Label", "Product Documentation/Web", "Producer Responsibility/ EDPs", "RQA Revision /Creation", "Specification Revision/ Creation", "Supply Chain", "Testing", "Trade Compliance", "Configuration Restriction", "Sales Operation", "Services (Product/Operation/Logistics)", "Annual Report", "TBD"]
            },
        }

def save_questions():
    with open('guided_questions.json', 'w') as f:
        json.dump(st.session_state.guided_questions, f, indent=2)

def load_password():
    try:
        with open('admin_password.hash', 'rb') as f:
            st.session_state.admin_password_hash = f.read()
    except FileNotFoundError:
        st.session_state.admin_password_hash = bcrypt.hashpw('admin'.encode('utf-8'), bcrypt.gensalt())
        with open('admin_password.hash', 'wb') as f:
            f.write(st.session_state.admin_password_hash)

def verify_password(password):
    return bcrypt.checkpw(password.encode('utf-8'), st.session_state.admin_password_hash)

def save_password(password):
    st.session_state.admin_password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    with open('admin_password.hash', 'wb') as f:
        f.write(st.session_state.admin_password_hash)

def read_file_content(file):
    file_extension = os.path.splitext(file.name)[1].lower()
    
    if file.size > MAX_FILE_SIZE:
        raise ValueError(f"File size ({file.size / (1024 * 1024):.2f} MB) exceeds the maximum allowed size ({MAX_FILE_SIZE / (1024 * 1024)} MB)")

    if file_extension == '.txt':
        return file.getvalue().decode('utf-8')
    elif file_extension == '.docx':
        return docx2txt.process(io.BytesIO(file.getvalue()))
    elif file_extension == '.pdf':
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file.getvalue()))
        return ' '.join(page.extract_text() for page in pdf_reader.pages)
    elif file_extension == '.csv':
        csv_reader = csv.reader(io.StringIO(file.getvalue().decode('utf-8')))
        return '\n'.join(','.join(row) for row in csv_reader)
    else:
        raise ValueError("Unsupported file format")

def get_relevant_file_chunk(query, file_content, top_k=1):
    # Break the file content into smaller chunks
    file_chunks = smart_chunk_prompt(file_content, max_tokens=800)  # Adjust max_tokens as needed for chunk size
    
    # Encode the chunks and the query using the embedding model
    embeddings = [embeddings_model.encode(chunk) for chunk in file_chunks]
    query_embedding = embeddings_model.encode([query])
    
    # Calculate cosine similarities between the query and each chunk
    similarities = cosine_similarity(query_embedding, embeddings).flatten()
    top_indices = np.argsort(similarities)[-top_k:]  # Get indices of the most similar chunks
    
    # Combine the top relevant chunks into a single context
    relevant_chunks = [file_chunks[i] for i in top_indices]
    return "\n\n".join(relevant_chunks)

def get_conversation_context(conversation, query, max_tokens=3000):
    context = []
    current_length = 0

    # Step 1: Retrieve and include the relevant chunk based on the current query
    if st.session_state.attached_file_content:
        relevant_chunk = get_relevant_file_chunk(query, st.session_state.attached_file_content, top_k=1)
        relevant_chunk_tokens = count_tokens(relevant_chunk)
        
        # Ensure the relevant chunk fits within the max token limit
        if relevant_chunk_tokens <= max_tokens:
            context.append({"role": "system", "content": f"Relevant Content from File:\n{relevant_chunk}"})
            current_length += relevant_chunk_tokens
        else:
            # Truncate the relevant chunk to fit within the token limit
            truncated_chunk = tokenizer.decode(tokenizer.encode(relevant_chunk)[:max_tokens])
            context.append({"role": "system", "content": f"Relevant Content from File:\n{truncated_chunk}"})
            current_length += count_tokens(truncated_chunk)
            return context  # No room left for conversation history

    # Step 2: Add as much of the conversation history as possible
    for message in reversed(conversation):
        message_tokens = count_tokens(message['content'])
        if current_length + message_tokens > max_tokens:
            # Truncate the message to fit within the remaining token limit
            available_tokens = max_tokens - current_length
            truncated_message = tokenizer.decode(tokenizer.encode(message['content'])[:available_tokens])
            context.insert(0, {"role": message['role'], "content": truncated_message})
            current_length += count_tokens(truncated_message)
            break  # Stop adding more messages once the limit is reached
        else:
            context.insert(0, message)
            current_length += message_tokens

    return context

# Fuzzy matching function for keywords
def fuzzy_match_keywords(prompt):
    # Assuming keywords_df is loaded with the keyword data
    checked_keywords = keywords_df[keywords_df['Checked'].notna()]
    best_match = process.extractOne(prompt, checked_keywords['Checked'])
    
    if best_match and best_match[1] > 75:  # Adjust threshold as needed
        matched_row = checked_keywords[checked_keywords['Checked'] == best_match[0]].iloc[0]
        keywords = matched_row['Keywords'].split(',')
        filtered_keywords = [kw.strip() for kw in keywords if not is_region_specific(kw.strip())]
        return ', '.join(filtered_keywords)
    else:
        return ""

def is_region_specific(keyword):
    region_specific_terms = ['USA', 'EU', 'China', 'Japan', 'Korea', 'Canada', 'Australia', 'UK', 'Germany', 'France', 'Italy', 'Spain']
    return any(term.lower() in keyword.lower() for term in region_specific_terms)

# Updated guided_prompt_creation function
def guided_prompt_creation():
    suggested_prompt = "Please summarize the attached document with the following considerations:\n\n"
    formatted_prompt = "Summary of your inputs:\n\n"
    
    for section, data in st.session_state.guided_questions.items():
        suggested_prompt += f"{section}:\n"
        formatted_prompt += f"**{section}:**\n"
        for question in data.get('questions', []):
            question_text = question.get('question', '')
            answer = st.session_state.guided_answers.get(question_text, '')
            
            suggested_prompt += f"- {question_text}: {answer}\n"
            formatted_prompt += f"- {question_text}: {answer}\n"
            
            # Handle follow-up questions for yes/no questions
            if question.get('type') == 'Yes/No' and answer.lower() in ['yes', 'no']:
                for follow_up in question.get('follow_up', []):
                    if follow_up['condition'].lower() == answer.lower():
                        follow_up_answer = st.session_state.guided_answers.get(follow_up['question'], '')
                        suggested_prompt += f"  - {follow_up['question']}: {follow_up_answer}\n"
                        formatted_prompt += f"  - {follow_up['question']}: {follow_up_answer}\n"
        
        suggested_prompt += "\n"
        formatted_prompt += "\n"

    # Add fuzzy matched keywords
    keywords = fuzzy_match_keywords(suggested_prompt)
    if keywords:
        suggested_prompt += f"\nRelevant Keywords: {keywords}\n\n"


    prompt_instructions = """
    Please provide a comprehensive summary for a bulletin based on these factors. Pretend that you are a regulatory engineer whose job is to interpret this document into an internal regulatory bulletin for engineers to follow some important compliance guidance. Do not focus on punishments or penalties. Please provide the summary with all the following sections, and all of them should be filled in with corresponding information:
    1) Program Requirements Summary: a 2-3 sentence, brief summary of the regulation.
    2) Regulation Publication Date: the date the regulation was published. If regulation has not been published, leave this blank.
    3) Enforcement Date: This is the effective date of the regulation.
    4) Enforcement based on: Type of enforcement
    5) Compliance Checkpoint: How is regulation enforced upon entry?
    6) Regulation Status: Type of Regulation Status
    7) What is current process: If a regulation revision, this will be a 2-3 sentence summary of the current process, if it is a new regulation, note that it is new
    8) What has changed from current process:  2-3 sentence summary of what is changing from existing regulation process.  This section is what is used for Bulletin email summaries. Character limit has been increased to 1000. Must ensure Summary in properties reflects same as Bulletin
    9) Key Details – Legislation Requirement: This section is the regulation requirements. What is needed to reach compliance.
    10) Requirement: Frequently used Requirements are listed in the table template, add additional requirements as required, and delete those not relevant.
    11) Dependency: Is the requirement dependent on another requirement in the table? If so, list the requirement that must be completed to meet the requirement.
    12) Details of Requirement: High level explanation of the regulatory requirement
    13) Wireless Technology Scope: For Wireless Programs only, leave blank if not related
    14) Detail Requirements: This is details of Regulation.  May include some tables and technical detail copied from regulation.  Should not, however be a straight copy/paste.
    """

    suggested_prompt += prompt_instructions
    formatted_prompt += "**Instructions for the AI:**\n" + prompt_instructions

    return suggested_prompt, formatted_prompt

def process_follow_up_question(follow_up):
    question_text = follow_up.get('question', '')
    question_type = follow_up.get('type', '')
    
    if question_type == 'Check-Box':
        options = st.multiselect(question_text, follow_up.get('options', []))
        return f"{question_text}: {', '.join(options)}"
    elif question_type == 'Yes/No':
        answer = st.radio(question_text, ['Yes', 'No', 'TBD'])
        return f"{question_text}: {answer}"
    elif question_type == 'Multiple':
        options = st.multiselect(question_text, follow_up.get('options', []))
        return f"{question_text}: {', '.join(options)}"
    elif question_type == 'Open':
        answer = st.text_input(question_text)
        return f"{question_text}: {answer}"
    
    return None

def count_tokens(text):
    return len(tokenizer.encode(text))

def smart_chunk_prompt(prompt, max_tokens=4000):
    tokens = tokenizer.encode(prompt)
    chunks = []
    current_chunk = []
    current_length = 0
    
    sentences = re.split('(?<=[.!?]) +', prompt)
    for sentence in sentences:
        sentence_tokens = tokenizer.encode(sentence)
        if current_length + len(sentence_tokens) > max_tokens and current_chunk:
            chunks.append(tokenizer.decode(current_chunk))
            current_chunk = []
            current_length = 0
        current_chunk.extend(sentence_tokens)
        current_length += len(sentence_tokens)
    
    if current_chunk:
        chunks.append(tokenizer.decode(current_chunk))
    
    return chunks

def add_instructions_to_chunk(chunk, original_prompt):
    parts = original_prompt.split("User Input:", 1)
    
    if len(parts) > 1:
        guided_prompt = parts[0].strip()
        user_input_and_file = parts[1].strip()
    else:
        guided_prompt = original_prompt
        user_input_and_file = ""

    guided_prompt = guided_prompt.split("Attached File Content:", 1)[0].strip()

    instructions = f"""
    Instructions based on the guided prompt:
    {guided_prompt}

    Note: This is a part of a larger document. For any sections where information is not available in this chunk, please write 'Information not available in this chunk.'

    User Input and/or File Content:
    {user_input_and_file}

    Chunk content:
    {chunk}
    """

    return instructions.strip()

def process_chunk(chunk, chunk_num, total_chunks, original_prompt):
    url = "https://opensource-challenger-api.prdlvgpu1.aiaccel.dell.com/v1/chat/completions"
    headers = {
        'accept': 'application/json',
        'api-key': os.environ["CHALLENGER_GENAI_API_KEY"],
        'Content-Type': 'application/json'
    }
    
    system_message = "You are a helpful AI assistant. Respond directly to the user without mentioning yourself in the third person or commenting on the nature of the response."
    
    if chunk_num > 1:
        chunk_with_instructions = add_instructions_to_chunk(chunk, original_prompt)
    else:
        chunk_with_instructions = chunk
    
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": chunk_with_instructions}
    ]
    
    data = {
        "model": MODEL,  
        "messages": messages,
        "temperature": 0.4,
        "top_p": 0.95,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": True
    }
    
    logger.debug(f"Processing chunk {chunk_num} of {total_chunks}")
    logger.debug(f"Request URL: {url}")
    logger.debug(f"Request Headers: {json.dumps(headers, indent=2)}")
    logger.debug(f"Request Payload: {json.dumps(data, indent=2)}")
    logger.debug(f"Total input tokens: {count_tokens(system_message) + count_tokens(chunk_with_instructions)}")
    
    try:
        with requests.post(url, headers=headers, json=data, stream=True, verify=False) as response:
            logger.debug(f"Response Status Code: {response.status_code}")
            logger.debug(f"Response Headers: {json.dumps(dict(response.headers), indent=2)}")
            
            response.raise_for_status()
            chunk_response = ""
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    logger.debug(f"Received line: {decoded_line}")
                    if decoded_line.startswith("data: "):
                        if decoded_line.strip() == "data: [DONE]":
                            break
                        try:
                            json_response = json.loads(decoded_line[6:])
                            if 'choices' in json_response and len(json_response['choices']) > 0:
                                delta = json_response['choices'][0].get('delta', {})
                                if 'content' in delta:
                                    chunk_response += delta['content']
                        except json.JSONDecodeError:
                            logger.error(f"Failed to decode JSON: {decoded_line}")
                            continue
            return chunk_response
    except requests.RequestException as e:
        logger.error(f"Request failed for chunk {chunk_num}: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response content: {e.response.text}")
        return f"Error processing chunk {chunk_num}: {str(e)}"

def process_chunks_parallel(chunks, original_prompt):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_chunk, chunk, i+1, len(chunks), original_prompt) 
                   for i, chunk in enumerate(chunks)]
        responses = []
        for future in concurrent.futures.as_completed(futures):
            responses.append(future.result())
    return responses

def process_summary_chunk(chunk, original_prompt):
    url = "https://opensource-challenger-api.prdlvgpu1.aiaccel.dell.com/v1/chat/completions"
    headers = {
        'accept': 'application/json',
        'api-key': os.environ["CHALLENGER_GENAI_API_KEY"],
        'Content-Type': 'application/json'
    }

    # Use the original prompt instruction as the base and append the chunk for data extraction
    instruction_match = re.search(r"Please provide .+?:\n", original_prompt, re.DOTALL)
    if instruction_match:
        instructions = instruction_match.group(0)
    else:
        instructions = original_prompt

    # Modify the prompt to request data extraction and filling in the blanks
    summary_prompt = f"{instructions}\n\nPlease extract relevant information from the following chunk to populate the instructions provided above:\n\n{chunk}"

    system_message = "You are a helpful AI assistant. Extract relevant information from the provided chunk and use it to populate the sections in the instructions. If information for a section is not available in the chunk, indicate it with 'Not applicable'."

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": summary_prompt}
    ]

    input_tokens = sum(count_tokens(message['content']) for message in messages)
    max_context_length = 8192
    available_tokens = max_context_length - input_tokens - 100

    if available_tokens <= 0:
        max_prompt_tokens = max_context_length - count_tokens(system_message) - 100
        prompt_tokens = tokenizer.encode(summary_prompt)[:max_prompt_tokens]
        summary_prompt = tokenizer.decode(prompt_tokens)
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": summary_prompt}
        ]
        available_tokens = max_context_length - count_tokens(system_message) - count_tokens(summary_prompt) - 100

    max_tokens = min(available_tokens, 4000)

    data = {
        "model": MODEL,  
        "messages": messages,
        "temperature": 0.4,
        "top_p": 0.95,
        "max_tokens": max_tokens,
        "stream": True
    }

    try:
        with requests.post(url, headers=headers, json=data, stream=True, verify=False) as response:
            summary_response = ""
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith("data: "):
                        if decoded_line.strip() == "data: [DONE]":
                            break
                        try:
                            json_response = json.loads(decoded_line[6:])
                            if 'choices' in json_response and len(json_response['choices']) > 0:
                                delta = json_response['choices'][0].get('delta', {})
                                if 'content' in delta:
                                    summary_response += delta['content']
                        except json.JSONDecodeError:
                            continue
            return summary_response
    except requests.RequestException as e:
        logger.error(f"Request failed during summarization: {str(e)}")
        return f"Error summarizing chunk: {str(e)}"

def summarize_responses(combined_response, original_prompt):
    chunks = smart_chunk_prompt(combined_response, max_tokens=4000)
    
    if len(chunks) == 1:
        return process_summary_chunk(chunks[0], original_prompt)
    
    summaries = process_chunks_parallel(chunks, original_prompt)
    
    combined_summary = combine_meaningful_parts(summaries)
    
    # After combining, ensure the final output includes the full instructions
    final_summary = f"{original_prompt}\n\n{combined_summary}"
    
    if count_tokens(final_summary) > 4000:
        return summarize_responses(final_summary, original_prompt)
    
    return final_summary

def combine_meaningful_parts(summaries):
    combined_parts = {}
    for summary in summaries:
        parts = summary.split('\n\n')
        for part in parts:
            if ':' in part:
                key, content = part.split(':', 1)
                key = key.strip()
                content = content.strip()
                if content.lower() not in ['not applicable', 'information not available in this chunk', 'n/a']:
                    if key in combined_parts:
                        combined_parts[key] += '\n' + content
                    else:
                        combined_parts[key] = content
    
    return '\n\n'.join([f"{key}: {value}" for key, value in combined_parts.items()])

def get_model_response(model, prompt):
    system_message = "You are a helpful AI assistant. Respond directly to the user without mentioning yourself in the third person or commenting on the nature of the response."
    
    max_chunk_tokens = MAX_TOKENS - count_tokens(system_message) - MAX_OUTPUT_TOKENS - BUFFER_TOKENS
    chunks = smart_chunk_prompt(prompt, max_chunk_tokens)
    
    if len(chunks) > 1:
        logger.info(f"Input split into {len(chunks)} chunks for processing.")
        responses = process_chunks_parallel(chunks, prompt)
        final_response = summarize_responses("\n\n".join(responses), prompt)
    else:
        final_response = process_chunk(chunks[0], 1, 1, prompt)
    
    return final_response

def get_relevant_context(query, top_k=3):
    if st.session_state.context_embeddings is None:
        return ""
    
    query_embedding = embeddings_model.encode([query])
    similarities = cosine_similarity(query_embedding, st.session_state.context_embeddings)[0]
    top_indices = np.argsort(similarities)[-top_k:]
    
    relevant_sentences = [st.session_state.context.split('.')[i] for i in top_indices]
    context = ' '.join(relevant_sentences)
    return context


# Streamlit UI
st.title("Regulatory Bulletin Assistant")

sidebar_container = st.sidebar.container()
# Sidebar
with sidebar_container:
    st.markdown('<div class="sidebar-image">', unsafe_allow_html=True)
    st.image("image/android-chrome-192x192.png")
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Chat", "Admin"])

st.markdown(
"""
<style>
.sidebar-image {
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 0;
}
.sidebar-image img {
    max-width: 50%;
    height: auto;
}
.footer {
    position: fixed;
    left: 0;
    bottom: 0;
    width: 100%;
    background-color: white;
    color: grey;
    text-align: center;
}
</style>
<div class="footer">
    <p>© 2024 DELL GPCE Team V.1.0.0</p>
</div>
""",
unsafe_allow_html=True
)

if page == "Chat":
    st.header("Chat Interface")

    # File upload
    if not st.session_state.file_uploaded:
        uploaded_file = st.file_uploader("Upload a file", type=["txt", "docx", "pdf", "csv"])
        if uploaded_file is not None:
            try:
                st.session_state.attached_file_content = read_file_content(uploaded_file)
                st.session_state.file_uploaded = True
                st.success("File uploaded successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Error uploading file: {str(e)}")
    
    # Guided questions
    elif not st.session_state.prompt_ready:
        st.subheader("Please answer the following questions:")
        for section, data in st.session_state.guided_questions.items():
            st.write(f"**{section}**")
            for question in data.get('questions', []):
                question_text = question.get('question', '')
                question_type = question.get('type', '')
                
                if question_text not in st.session_state.guided_answers:
                    st.session_state.guided_answers[question_text] = ''
                
                if question_type in ['Check-Box', 'Multiple']:
                    if question_text not in st.session_state.checkbox_selections:
                        st.session_state.checkbox_selections[question_text] = []
                    
                    options = question.get('options', [])
                    st.write(question_text)
                    for option in options:
                        checkbox_key = f"{question_text}_{option}"
                        is_checked = st.checkbox(option, key=checkbox_key, value=option in st.session_state.checkbox_selections[question_text])
                        if is_checked and option not in st.session_state.checkbox_selections[question_text]:
                            st.session_state.checkbox_selections[question_text].append(option)
                        elif not is_checked and option in st.session_state.checkbox_selections[question_text]:
                            st.session_state.checkbox_selections[question_text].remove(option)
                    
                    st.session_state.guided_answers[question_text] = ', '.join(st.session_state.checkbox_selections[question_text])
                
                elif question_type == 'Yes/No':
                    answer = st.radio(question_text, ['Yes', 'No', 'TBD'], index=['Yes', 'No', 'TBD'].index(st.session_state.guided_answers[question_text]) if st.session_state.guided_answers[question_text] in ['Yes', 'No', 'TBD'] else 0)
                    st.session_state.guided_answers[question_text] = answer
                    
                    # Handle follow-up questions
                    if answer.lower() in ['yes', 'no']:
                        for follow_up in question.get('follow_up', []):
                            if follow_up['condition'].lower() == answer.lower():
                                follow_up_text = follow_up['question']
                                follow_up_type = follow_up['type']
                                
                                if follow_up_type in ['Check-Box', 'Multiple']:
                                    options = st.multiselect(follow_up_text, follow_up['options'])
                                    st.session_state.guided_answers[follow_up_text] = ', '.join(options)
                                elif follow_up_type == 'Open':
                                    follow_up_answer = st.text_input(follow_up_text, value=st.session_state.guided_answers.get(follow_up_text, ''))
                                    st.session_state.guided_answers[follow_up_text] = follow_up_answer
                
                elif question_type == 'Open':
                    answer = st.text_input(question_text, value=st.session_state.guided_answers[question_text])
                    st.session_state.guided_answers[question_text] = answer
        
        if st.button("Submit Answers"):
            st.session_state.prompt_ready = True
            st.rerun()

    # Show constructed prompt and chat interface
    else:
        if not st.session_state.summary_generated:
            suggested_prompt, formatted_prompt = guided_prompt_creation()
            
            st.subheader("Constructed Prompt Based on Your Answers")
            st.markdown(formatted_prompt)
            
            st.subheader("Generated Summary")
            with st.chat_message("assistant"):
                message_placeholder = st.empty()

                full_prompt = f"{suggested_prompt}\n\nPlease provide a summary based on the above considerations and the following attached file content:\n\n{st.session_state.attached_file_content}"

                context = get_relevant_context(full_prompt)
                full_prompt = f"Context: {context}\n\n{full_prompt}"

                try:
                    full_response = get_model_response(MODEL, full_prompt)
                    message_placeholder.markdown(full_response)
                except Exception as e:
                    error_message = f"An error occurred while generating the summary: {str(e)}"
                    st.error(error_message)
                    logger.error(error_message)
                    full_response = "I apologize, but an error occurred while generating the summary. Please try again or contact support if the problem persists."
                    message_placeholder.markdown(full_response)
            
            if st.session_state.current_conversation is None:
                st.session_state.current_conversation = f"Chat {len(st.session_state.conversations) + 1}"
                st.session_state.conversations[st.session_state.current_conversation] = []
            
            st.session_state.conversations[st.session_state.current_conversation].append({"role": "assistant", "content": full_response})
            st.session_state.summary_generated = True
            st.rerun()

        st.subheader("Chat")
        if st.session_state.current_conversation:
            for message in st.session_state.conversations[st.session_state.current_conversation]:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        # Chat input with enhanced unique key
        chat_input_key = f"chat_input_{page}_{st.session_state.current_conversation}_{st.session_state.chat_counter}"
        prompt = st.chat_input("What would you like to ask about the document?", key=chat_input_key)
        if prompt:
            st.session_state.chat_counter += 1
            
            st.session_state.conversations[st.session_state.current_conversation].append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                message_placeholder.markdown("Generating response... Please wait.")
                query = prompt  # or any other variable that contains the current query
                conversation_context = get_conversation_context(st.session_state.conversations[st.session_state.current_conversation], query)
                
                context_prompt = "Based on the previous conversation and summary, please answer the following question:\n\n"
                for message in conversation_context:
                    context_prompt += f"{message['role'].capitalize()}: {message['content']}\n\n"
                context_prompt += f"User: {prompt}\n\nAssistant:"

                try:
                    full_response = get_model_response(MODEL, context_prompt)
                    message_placeholder.markdown(full_response)
                    st.session_state.conversations[st.session_state.current_conversation].append({"role": "assistant", "content": full_response})
                except Exception as e:
                    st.error(f"An error occurred while generating the response: {str(e)}")
                    logger.error(f"Error in model response: {str(e)}")
            
            st.rerun()
            
        # Reset button
        if st.button("Start New Analysis"):
            st.session_state.file_uploaded = False
            st.session_state.guided_answers = {}
            st.session_state.prompt_ready = False
            st.session_state.attached_file_content = None
            st.session_state.chat_counter = 0  # Reset the chat counter
            st.session_state.summary_generated = False  # Reset the summary generation flag
            st.rerun()


elif page == "Admin":
    st.header("Admin Section")
    
    if not st.session_state.is_admin:
        password = st.text_input("Enter admin password", type="password")
        if st.button("Login"):
            if verify_password(password):
                st.session_state.is_admin = True
                st.experimental_rerun()
            else:
                st.error("Incorrect password")
    else:
        st.success("Logged in as admin")
        
        if st.button("Logout"):
            st.session_state.is_admin = False
            st.experimental_rerun()
        
        if st.button("Change Password"):
            new_password = st.text_input("Enter new password", type="password")
            if st.button("Confirm Change"):
                save_password(new_password)
                st.success("Password changed successfully!")

        st.header("Question Management")
        
        # Add new section
        with st.expander("Add New Section"):
            new_section = st.text_input("New Section Name")
            if st.button("Add Section", key="add_section_button"):
                if new_section and new_section not in st.session_state.guided_questions:
                    st.session_state.guided_questions[new_section] = {"questions": []}
                    save_questions()
                    st.success(f"Section '{new_section}' added successfully!")
                    st.experimental_rerun()
                elif new_section in st.session_state.guided_questions:
                    st.error("Section already exists!")
        
        # Manage existing sections
        for section_index, section in enumerate(st.session_state.guided_questions):
            with st.expander(f"Manage {section}"):
                st.subheader(section)
                
                # Remove section
                if st.button(f"Remove Section: {section}", key=f"remove_section_{section_index}"):
                    if st.checkbox(f"Are you sure you want to remove the entire '{section}' section?", key=f"confirm_remove_section_{section_index}"):
                        del st.session_state.guided_questions[section]
                        save_questions()
                        st.success(f"Section '{section}' removed successfully!")
                        st.experimental_rerun()
                
                # Add new question to section
                st.subheader("Add New Question")
                new_question = st.text_input(f"New Question for {section}", key=f"new_question_{section_index}")
                new_type = st.selectbox(f"Question Type for {section}", ["Check-Box", "Yes/No", "Multiple", "Open"], key=f"new_type_{section_index}")

                options = []
                follow_up_questions = []
                if new_type in ["Check-Box", "Multiple"]:
                    options = st.text_area(f"Options (one per line)", key=f"options_{section_index}").split('\n')
                    options = [opt.strip() for opt in options if opt.strip()]

                if new_type == "Yes/No":
                    for condition in ["yes", "no"]:
                        st.subheader(f"Follow-up Question for '{condition.capitalize()}' answer")
                        follow_up_question = st.text_input(f"Follow-up Question ({condition})", key=f"follow_up_question_{section_index}_{condition}")
                        follow_up_type = st.selectbox(f"Follow-up Question Type ({condition})", ["Check-Box", "Multiple", "Open"], key=f"follow_up_type_{section_index}_{condition}")
                        
                        follow_up_options = []
                        if follow_up_type in ["Check-Box", "Multiple"]:
                            follow_up_options = st.text_area(f"Follow-up Options ({condition}, one per line)", key=f"follow_up_options_{section_index}_{condition}").split('\n')
                            follow_up_options = [opt.strip() for opt in follow_up_options if opt.strip()]
                        
                        if follow_up_question:
                            follow_up_questions.append({
                                "question": follow_up_question,
                                "type": follow_up_type,
                                "options": follow_up_options,
                                "condition": condition
                            })

                if st.button(f"Add Question to {section}", key=f"add_question_{section_index}"):
                    if new_question and new_type:
                        new_question_data = {
                            "question": new_question,
                            "type": new_type
                        }
                        if new_type in ["Check-Box", "Multiple"]:
                            new_question_data["options"] = options
                        if new_type == "Yes/No" and follow_up_questions:
                            new_question_data["follow_up"] = follow_up_questions
                        
                        st.session_state.guided_questions[section]["questions"].append(new_question_data)
                        save_questions()
                        st.success("Question added successfully!")
                        st.rerun()

                # Update the "Edit Question" part
                for i, question in enumerate(st.session_state.guided_questions[section]["questions"]):
                    st.subheader(f"Question {i+1}")
                    st.write(f"Question: {question['question']}")
                    st.write(f"Type: {question['type']}")
                    if 'options' in question:
                        st.write(f"Options: {', '.join(question['options'])}")
                    
                    if st.button(f"Edit Question {i+1}", key=f"edit_question_{section_index}_{i}"):
                        edited_question = st.text_input("Edit Question", value=question['question'], key=f"edit_question_text_{section_index}_{i}")
                        edited_type = st.selectbox("Edit Question Type", ["Check-Box", "Yes/No", "Multiple", "Open"], 
                                                index=["Check-Box", "Yes/No", "Multiple", "Open"].index(question['type']),
                                                key=f"edit_question_type_{section_index}_{i}")
                        
                        edited_options = []
                        edited_follow_up_questions = []
                        
                        if edited_type in ["Check-Box", "Multiple"]:
                            options_text = "\n".join(question.get('options', []))
                            edited_options_text = st.text_area("Edit Options (one per line)", value=options_text, key=f"edit_options_{section_index}_{i}")
                            edited_options = [opt.strip() for opt in edited_options_text.split('\n') if opt.strip()]
                        
                        if edited_type == "Yes/No":
                            for condition in ["yes", "no"]:
                                st.subheader(f"Follow-up Question for '{condition.capitalize()}' answer")
                                existing_follow_up = next((f for f in question.get('follow_up', []) if f['condition'] == condition), None)
                                
                                follow_up_question = st.text_input(f"Follow-up Question ({condition})", 
                                                                value=existing_follow_up['question'] if existing_follow_up else "",
                                                                key=f"edit_follow_up_question_{section_index}_{i}_{condition}")
                                follow_up_type = st.selectbox(f"Follow-up Question Type ({condition})", 
                                                            ["Check-Box", "Multiple", "Open"],
                                                            index=["Check-Box", "Multiple", "Open"].index(existing_follow_up['type']) if existing_follow_up else 0,
                                                            key=f"edit_follow_up_type_{section_index}_{i}_{condition}")
                                
                                follow_up_options = []
                                if follow_up_type in ["Check-Box", "Multiple"]:
                                    options_text = "\n".join(existing_follow_up.get('options', [])) if existing_follow_up else ""
                                    follow_up_options_text = st.text_area(f"Follow-up Options ({condition}, one per line)", 
                                                                        value=options_text,
                                                                        key=f"edit_follow_up_options_{section_index}_{i}_{condition}")
                                    follow_up_options = [opt.strip() for opt in follow_up_options_text.split('\n') if opt.strip()]
                                
                                if follow_up_question:
                                    edited_follow_up_questions.append({
                                        "question": follow_up_question,
                                        "type": follow_up_type,
                                        "options": follow_up_options,
                                        "condition": condition
                                    })
                        
                        if st.button("Save Edits", key=f"save_edits_{section_index}_{i}"):
                            st.session_state.guided_questions[section]["questions"][i]["question"] = edited_question
                            st.session_state.guided_questions[section]["questions"][i]["type"] = edited_type
                            if edited_type in ["Check-Box", "Multiple"]:
                                st.session_state.guided_questions[section]["questions"][i]["options"] = edited_options
                            if edited_type == "Yes/No":
                                st.session_state.guided_questions[section]["questions"][i]["follow_up"] = edited_follow_up_questions
                            save_questions()
                            st.success("Question edited successfully!")
                            st.rerun()
                    
                    # Remove question
                    if st.button(f"Remove Question {i+1}", key=f"remove_question_{section_index}_{i}"):
                        if st.checkbox(f"Are you sure you want to remove Question {i+1}?", key=f"confirm_remove_question_{section_index}_{i}"):
                            st.session_state.guided_questions[section]["questions"].pop(i)
                            save_questions()
                            st.success("Question removed successfully!")
                            st.experimental_rerun()
                    
                    st.write("---")

# Initialize the app
if __name__ == "__main__":
    load_questions()
    load_password()