import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox, simpledialog
import requests
import json
import threading
import os
import pickle
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import docx2txt
import PyPDF2
import csv
import io

class CheckboxDialog(tk.Toplevel):
    def __init__(self, parent, title, options):
        super().__init__(parent)
        self.title(title)
        self.result = []
        
        for option in options:
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(self, text=option, variable=var)
            cb.pack(anchor="w", padx=10, pady=5)
            self.result.append((option, var))
        
        ttk.Button(self, text="OK", command=self.destroy).pack(pady=10)

class LLMPlayground:
    def __init__(self, master):
        self.master = master
        master.title("LLM Playground")
        master.geometry("1200x800")

        self.conversations = {}
        self.current_conversation = None
        self.context = ""
        self.embeddings_model = SentenceTransformer('all-MiniLM-L6-v2')
        self.context_embeddings = None
        self.attached_file_content = None
        self.is_generating = False
        self.current_attachment = None

        self.create_widgets()
        self.apply_style()

    def create_widgets(self):
        # Create main frame
        main_frame = ttk.Frame(self.master)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Create sidebar
        sidebar = ttk.Frame(main_frame, width=250, relief='groove', borderwidth=2)
        sidebar.pack(side='left', fill='y', padx=(0, 10))

        # Create chat area
        chat_area = ttk.Frame(main_frame)
        chat_area.pack(side='right', fill='both', expand=True)

        # Sidebar widgets
        ttk.Button(sidebar, text="New Chat", command=self.new_chat).pack(pady=5, fill='x')
        ttk.Button(sidebar, text="Save Conversations", command=self.save_conversations).pack(pady=5, fill='x')
        ttk.Button(sidebar, text="Load Conversations", command=self.load_conversations).pack(pady=5, fill='x')
        ttk.Button(sidebar, text="Clear Chat History", command=self.clear_chat_history).pack(pady=5, fill='x')
        
        ttk.Label(sidebar, text="Your conversations").pack(pady=5)
        self.conversation_listbox = tk.Listbox(sidebar)
        self.conversation_listbox.pack(pady=5, padx=5, fill='x')
        self.conversation_listbox.bind('<<ListboxSelect>>', self.on_conversation_select)

        ttk.Label(sidebar, text="Select Ollama Model").pack(pady=5)
        self.model_combobox = ttk.Combobox(sidebar, values=self.get_ollama_models(), width=30)
        self.model_combobox.pack(pady=5, padx=5, fill='x')
        if "llama3" in self.model_combobox['values']:
            self.model_combobox.set("llama3")
        else:
            self.model_combobox.set(self.model_combobox['values'][0])

        ttk.Label(sidebar, text="Temperature").pack(pady=5)
        self.temperature_scale = ttk.Scale(sidebar, from_=0, to=1, orient='horizontal')
        self.temperature_scale.set(0.7)
        self.temperature_scale.pack(pady=5, padx=5, fill='x')

        ttk.Label(sidebar, text="Max Tokens").pack(pady=5)
        self.max_tokens_entry = ttk.Entry(sidebar)
        self.max_tokens_entry.insert(0, "8192")
        self.max_tokens_entry.pack(pady=5, padx=5, fill='x')

        ttk.Button(sidebar, text="Upload Context for RAG", command=self.upload_context_for_rag).pack(pady=5, fill='x')

        # Chat area widgets
        self.chat_display = scrolledtext.ScrolledText(chat_area, state='disabled')
        self.chat_display.pack(pady=10, fill='both', expand=True)

        input_frame = ttk.Frame(chat_area)
        input_frame.pack(fill='x', pady=10)

        self.user_input = ttk.Entry(input_frame)
        self.user_input.pack(side='left', fill='x', expand=True)

        ttk.Button(input_frame, text="Attach File", command=self.attach_file).pack(side='left', padx=5)
        ttk.Button(input_frame, text="Send", command=self.send_message).pack(side='left')

        # Configure text tags
        self.chat_display.tag_configure('user', foreground='blue')
        self.chat_display.tag_configure('user_message', foreground='black')
        self.chat_display.tag_configure('assistant', foreground='green')
        self.chat_display.tag_configure('assistant_message', foreground='black')

    def apply_style(self):
        style = ttk.Style()
        style.theme_use('clam')

        style.configure('.', background='#f0f0f0', foreground='#333333')
        style.configure('TButton', background='#4CAF50', foreground='white')
        style.map('TButton', background=[('active', '#45a049')])
        style.configure('TEntry', fieldbackground='white')
        style.configure('TCombobox', fieldbackground='white')
        style.configure('TScale', background='#4CAF50')

        default_font = ('Helvetica', 10)
        heading_font = ('Helvetica', 12, 'bold')
        
        style.configure('.', font=default_font)
        style.configure('TButton', font=default_font)
        style.configure('TLabel', font=heading_font)

        self.chat_display.configure(font=default_font, background='white', foreground='#333333')
        self.conversation_listbox.configure(font=default_font, background='white', foreground='#333333')

    def guided_prompt_creation(self):
        print("Starting guided prompt creation...")
        # Field checkboxes
        fields = [
            "EMC", "Safety", "Wireless", "Telecom/PSTN", "Materials", "Energy",
            "Packaging", "Cybersecurity", "US Federal", "Others"
        ]
        field_dialog = CheckboxDialog(self.master, "Select Fields", fields)
        self.master.wait_window(field_dialog)
        selected_fields = [option for option, var in field_dialog.result if var.get()]

        # Impact checkboxes
        impacts = [
            "Certification / DOC/ Registration", "New/ Revision", "Regulatory Filing",
            "Design Change", "Component impact", "Cost impact", "Factory inspection",
            "Label – New/ Revised Packaging Label", "Logistics", "Product Label",
            "Product Documentation/Web", "Producer Responsibility/ EDPs",
            "RQA Revision /Creation", "Specification Revision/ Creation", "Supply Chain",
            "Testing", "Trade Compliance", "Configuration Restriction", "Sales Operation",
            "Services (Product/Operation/Logistics)", "Annual Report", "TBD"
        ]
        impact_dialog = CheckboxDialog(self.master, "Select Impacts", impacts)
        self.master.wait_window(impact_dialog)
        selected_impacts = [option for option, var in impact_dialog.result if var.get()]

        # General and Sub-Questions
        answers = {}
        
        def ask_sub_questions(main_question, sub_questions):
            if messagebox.askyesno("Question", main_question):
                for sub_q in sub_questions:
                    if isinstance(sub_q, tuple):
                        sub_dialog = CheckboxDialog(self.master, sub_q[0], sub_q[1])
                        self.master.wait_window(sub_dialog)
                        answers[sub_q[0]] = [option for option, var in sub_dialog.result if var.get()]
                    else:
                        answer = messagebox.askyesno("Sub-Question", sub_q)
                        answers[sub_q] = "Yes" if answer else "No"
            else:
                answers[main_question] = "No"

        ask_sub_questions("Does it impact product 'Design change'?", [])
        ask_sub_questions("Does it impact product 'Label'?", 
                        [("Label changes:", ["Additional statement", "New logo", "Color change", "Others"])])
        ask_sub_questions("Does it impact 'Packaging'?", 
                        [("Packaging changes:", ["Additional statement", "New logo", "Others"])])
        ask_sub_questions("Does it impact 'User manual' (hard copy)?", 
                        [("Hard copy changes:", ["SERI", "QR card"])])
        ask_sub_questions("Does it impact 'User manual' (soft copy)?", 
                        ["Website (JIRA - e.g. TW RoHS Table)", 
                        "Documentation (dell.com – e.g. owner's manual, service manual)"])

        # Construct the suggested prompt
        suggested_prompt = "Please summarize the attached document with the following considerations:\n\n"
        suggested_prompt += f"Fields: {', '.join(selected_fields)}\n\n"
        suggested_prompt += f"Impacts: {', '.join(selected_impacts)}\n\n"
        suggested_prompt += "Specific impacts and changes:\n"
        for question, answer in answers.items():
            if isinstance(answer, list):
                suggested_prompt += f"- {question} {', '.join(answer)}\n"
            else:
                suggested_prompt += f"- {question} {answer}\n"

        print(f"Suggested prompt: {suggested_prompt}")
        return suggested_prompt

    def upload_context_for_rag(self):
        file_path = filedialog.askopenfilename(filetypes=[
            ("Text files", "*.txt"),
            ("Word documents", "*.docx"),
            ("PDF files", "*.pdf"),
            ("CSV files", "*.csv")
        ])
        if file_path:
            self.context = self.read_file_content(file_path)
            self.context_embeddings = self.embeddings_model.encode(self.context.split('.'))
            messagebox.showinfo("Success", "Context file uploaded successfully for RAG!")

    def attach_file(self):
        file_path = filedialog.askopenfilename(filetypes=[
            ("Text files", "*.txt"),
            ("Word documents", "*.docx"),
            ("PDF files", "*.pdf"),
            ("CSV files", "*.csv")
        ])
        if file_path:
            self.attached_file_content = self.read_file_content(file_path)
            file_name = os.path.basename(file_path)
            self.user_input.insert(tk.END, f" [Attached: {file_name}]")

    def read_file_content(self, file_path):
        _, file_extension = os.path.splitext(file_path)
        
        if file_extension == '.txt':
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        elif file_extension == '.docx':
            content = docx2txt.process(file_path)
            print(f"Docx content length: {len(content)}")
            return content
        elif file_extension == '.pdf':
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                return ' '.join(page.extract_text() for page in pdf_reader.pages)
        elif file_extension == '.csv':
            with open(file_path, 'r', encoding='utf-8') as file:
                csv_reader = csv.reader(file)
                return '\n'.join(','.join(row) for row in csv_reader)
        else:
            return "Unsupported file format"

    def send_message(self):
        if self.is_generating:
            return
        
        user_input = self.user_input.get()
        user_input_hide = user_input
        if not user_input and not self.attached_file_content:
            return

        # Start the guided prompt creation process if a file is attached
        if self.attached_file_content:
            suggested_prompt = self.guided_prompt_creation()
            if suggested_prompt:
                user_input += suggested_prompt
                user_input_hide += suggested_prompt
                user_input_hide += "\nPlease provide a comprehensive summary for a bulletin based on these factors.Pretend that you are a regulatory engineer whose job is to interpret this document into an internal regulatory bulletin for engineers to follow some important compliance guidance, do not put focus on punishments or penalties. I want the summary be provided with all the following sections, and all of them should be filled in with corresponding information\n" + \
                                "1)	Program Requirements Summary, a 2-3 sentence, brief summary of the regulation.\n" + \
                                "2)	Regulation Publication Date, the date the regulation was published.   If regulation has not been published, leave this blank.\n" + \
                                "3)	Enforcement Date: This is the effective date of the regulation.\n" + \
                                "4)	Enforcement based on: Type of enforcement\n" + \
                                "5)	Compliance Checkpoint: How is regulation enforced upon entry?\n" + \
                                "6)	Regulation Status: Type of Regulation Status\n" + \
                                "7)	What is current process: If a regulation revision, this will be a 2-3 sentence summary of the current process, if it is a new regulation, note that it is new\n" + \
                                "8)	What has changed from current process:  2-3 sentence summary of what is changing from existing regulation process.  This section is what is used for Bulletin email summaries. Character limit has been increased to 1000. Must ensure Summary in properties reflects same as Bulletin\n" + \
                                "9)	Key Details – Legislation Requirement: This section is the regulation requirements. What is needed to reach compliance.\n" + \
                                "10) Requirement: Frequently used Requirements are listed in the table template, add additional requirements as required, and delete those not relevant.\n" + \
                                "11) Dependency: Is the requirement dependent on another requirement in the table? If so, list the requirement that must be completed to meet the requirement.\n" + \
                                "12) Details of Requirement: High level explanation of the regulatory requirement\n" + \
                                "13) Wireless Technology Scope: For Wireless Programs only, leave blank if not related\n" + \
                                "14) Detail Requirements: This is details of Regulation.  May include some tables and technical detail copied from regulation.  Should not, however be a straight copy/paste.\n" 

        display_message = user_input
        full_message = user_input_hide

        if self.attached_file_content:
            display_message += "\n[Attached file content not displayed]"
            full_message += f"\n\nAttached file content:\n{self.attached_file_content}"
            print(full_message)

        if self.current_conversation is None:
            self.new_chat()

        self.conversations[self.current_conversation].append({"role": "user", "content": display_message, "full_content": full_message})
        self.update_chat_display()
        self.user_input.delete(0, tk.END)

        model = self.model_combobox.get()
        if model != "Select a model":
            threading.Thread(target=self.get_model_response, args=(model, full_message)).start()
            print(full_message)

        self.attached_file_content = None  # Reset after sending
        
    def get_ollama_models(self):
        try:
            response = requests.get("http://localhost:11434/api/tags")
            models = response.json().get("models", [])
            return [model["name"] for model in models]  # Return the full model name
        except requests.exceptions.RequestException:
            return []

    def new_chat(self):
        chat_name = f"Chat {len(self.conversations) + 1}"
        self.conversations[chat_name] = []
        self.conversation_listbox.insert(tk.END, chat_name)
        self.current_conversation = chat_name
        self.update_chat_display()

    def on_conversation_select(self, event):
        selection = event.widget.curselection()
        if selection:
            self.current_conversation = event.widget.get(selection[0])
            self.update_chat_display()

    def update_chat_display(self):
        self.chat_display.config(state='normal')
        self.chat_display.delete('1.0', tk.END)
        for message in self.conversations.get(self.current_conversation, []):
            if message['role'] == 'user':
                self.chat_display.insert(tk.END, f"User: ", 'user')
                self.chat_display.insert(tk.END, f"{message['content']}\n\n", 'user_message')
            else:
                self.chat_display.insert(tk.END, f"Assistant: ", 'assistant')
                self.chat_display.insert(tk.END, f"{message['content']}\n\n", 'assistant_message')
        self.chat_display.config(state='disabled')
        self.chat_display.see(tk.END)

    def get_model_response(self, model, prompt):
        self.is_generating = True
        self.user_input.config(state='disabled')
        
        self.chat_display.config(state='normal')
        self.chat_display.insert(tk.END, "Assistant: Generating response...\n", 'assistant')
        self.chat_display.config(state='disabled')
        self.chat_display.see(tk.END)

        try:
            context = self.get_relevant_context(prompt)
            
            url = "http://localhost:11434/api/generate"
            data = {
                "model": model,
                "prompt": f"Context: {context}\n\nUser: {prompt}",
                "temperature": self.temperature_scale.get(),
                "options": {
                    "num_ctx": 8192
                },
                "max_tokens": int(self.max_tokens_entry.get())
            }
            print(f"Prompt length: {len(data['prompt'])}")
            
            response = requests.post(url, json=data, stream=True)
            full_response = ""
            
            for line in response.iter_lines():
                if line:
                    json_response = json.loads(line)
                    if 'response' in json_response:
                        chunk = json_response['response']
                        full_response += chunk
                        self.master.after(0, self.update_response, full_response)

            self.conversations[self.current_conversation].append({"role": "assistant", "content": full_response})
            self.master.after(0, self.update_chat_display)
        except requests.exceptions.RequestException as e:
            self.master.after(0, self.show_error_popup, str(e))
        finally:
            self.is_generating = False
            self.user_input.config(state='normal')


    def update_response(self, response_so_far):
        self.chat_display.config(state='normal')
        self.chat_display.delete('1.0', tk.END)
        for message in self.conversations[self.current_conversation]:
            if message['role'] == 'user':
                self.chat_display.insert(tk.END, f"User: ", 'user')
                self.chat_display.insert(tk.END, f"{message['content']}\n\n", 'user_message')
            else:
                self.chat_display.insert(tk.END, f"Assistant: ", 'assistant')
                self.chat_display.insert(tk.END, f"{message['content']}\n\n", 'assistant_message')
        self.chat_display.insert(tk.END, f"Assistant: {response_so_far}", 'assistant_message')
        self.chat_display.config(state='disabled')
        self.chat_display.see(tk.END)

    def show_error_popup(self, error_message):
        messagebox.showerror("Error", error_message)

    def get_relevant_context(self, query, top_k=3):
        if self.context_embeddings is None:
            return ""
        
        query_embedding = self.embeddings_model.encode([query])
        similarities = cosine_similarity(query_embedding, self.context_embeddings)[0]
        top_indices = np.argsort(similarities)[-top_k:]
        
        relevant_sentences = [self.context.split('.')[i] for i in top_indices]
        context = ' '.join(relevant_sentences)
        print(f"Relevant context length: {len(context)}")
        return context

    def save_conversations(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".pkl")
        if file_path:
            with open(file_path, 'wb') as file:
                pickle.dump(self.conversations, file)
            messagebox.showinfo("Success", "Conversations saved successfully!")

    def load_conversations(self):
        file_path = filedialog.askopenfilename(filetypes=[("Pickle files", "*.pkl")])
        if file_path:
            with open(file_path, 'rb') as file:
                self.conversations = pickle.load(file)
            self.conversation_listbox.delete(0, tk.END)
            for chat_name in self.conversations.keys():
                self.conversation_listbox.insert(tk.END, chat_name)
            messagebox.showinfo("Success", "Conversations loaded successfully!")

    def clear_chat_history(self):
        if self.current_conversation:
            self.conversations[self.current_conversation] = []
            self.update_chat_display()
            messagebox.showinfo("Success", "Chat history cleared!")

    def chunk_and_truncate(self, text, max_tokens=8192):
        words = text.split()
        chunks = []
        current_chunk = []
        current_token_count = 0

        for word in words:
            if current_token_count + len(word.split()) > max_tokens:
                chunks.append(' '.join(current_chunk))
                current_chunk = [word]
                current_token_count = len(word.split())
            else:
                current_chunk.append(word)
                current_token_count += len(word.split())

        if current_chunk:
            chunks.append(' '.join(current_chunk))

        return chunks

if __name__ == "__main__":
    root = tk.Tk()
    app = LLMPlayground(root)
    root.mainloop()