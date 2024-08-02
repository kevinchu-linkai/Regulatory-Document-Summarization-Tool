import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox, simpledialog
import requests
import json
import threading
import bcrypt
import os
import pickle
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import docx2txt
import PyPDF2
import csv
import io

class GuidedQuestionDialog(tk.Toplevel):
    def __init__(self, parent, title, question_data):
        super().__init__(parent)
        self.title(title)
        self.result = None  # Initialize self.result to None by default
        self.question_data = question_data
        
        # Create the appropriate widget based on the question type
        if question_data['type'] == 'checkbox':
            self.create_checkbox_dialog(question_data['options'])
        elif question_data['type'] == 'yesno':
            self.create_yesno_dialog(question_data['question'])
        elif question_data['type'] == 'multiple':
            self.create_multiple_dialog(question_data['question'], question_data['options'])
        elif question_data['type'] == 'open':
            self.create_open_dialog(question_data['question'])

    def create_checkbox_dialog(self, options):
        self.result = []
        for option in options:
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(self, text=option, variable=var)
            cb.pack(anchor="w", padx=10, pady=5)
            self.result.append((option, var))
        
        self.add_ok_button()
        self.adjust_window_size(len(options))

    def create_yesno_dialog(self, question):
        label = tk.Label(self, text=question)
        label.pack(anchor="w", padx=10, pady=5)
        
        var = tk.StringVar(value="No")
        ttk.Radiobutton(self, text="Yes", variable=var, value="Yes").pack(anchor="w", padx=10, pady=5)
        ttk.Radiobutton(self, text="No", variable=var, value="No").pack(anchor="w", padx=10, pady=5)
        
        self.result = var
        self.add_ok_button()
        self.adjust_window_size(2)

    def create_multiple_dialog(self, question, options):
        label = tk.Label(self, text=question)
        label.pack(anchor="w", padx=10, pady=5)
        
        self.result = []
        for option in options:
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(self, text=option, variable=var)
            cb.pack(anchor="w", padx=10, pady=5)
            self.result.append((option, var))
        
        self.add_ok_button()
        self.adjust_window_size(len(options))

    def create_open_dialog(self, question):
        label = tk.Label(self, text=question)
        label.pack(anchor="w", padx=10, pady=5)
        
        text_entry = tk.Text(self, height=4, width=40, wrap=tk.WORD)
        text_entry.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        
        self.result = text_entry
        self.add_ok_button()
        self.adjust_window_size(1)

    def add_ok_button(self):
        ttk.Button(self, text="OK", command=self.on_ok).pack(pady=10)

    def on_ok(self):
        if isinstance(self.result, tk.Text):
            self.result = self.result.get("1.0", tk.END).strip()
        self.destroy()

    def adjust_window_size(self, item_count):
        # Adjust the size of the window based on the content
        base_height = 100  # Base height for title and buttons
        item_height = 30  # Height per item
        width = 400  # Fixed width
        height = base_height + item_height * item_count
        self.geometry(f"{width}x{height}")
        self.minsize(width, height)
        
# Add this class for tooltips
class CreateToolTip(object):
    def __init__(self, widget, text='widget info'):
        self.widget = widget
        self.text = text
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.close)

    def enter(self, event=None):
        x = self.widget.winfo_rootx() + self.widget.winfo_width()
        y = self.widget.winfo_rooty() + self.widget.winfo_height()//2
        # creates a toplevel window
        self.tw = tk.Toplevel(self.widget)
        # Leaves only the label and removes the app window
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tw, text=self.text, justify='left',
                       background='yellow', relief='solid', borderwidth=1,
                       font=("times", "8", "normal"))
        label.pack(ipadx=1)

    def close(self, event=None):
        if hasattr(self, 'tw'):
            self.tw.destroy()
            del self.tw
        
class QuestionManager(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Question Manager")
        self.geometry("800x600")  # Set a minimum size
        self.minsize(800, 600)    # Prevent resizing smaller than this
        self.create_widgets()
        
        # Load and display existing questions from JSON
        self.load_questions()
        self.populate_sections()

    def create_widgets(self):
        # Left side: Section list
        left_frame = ttk.Frame(self)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.section_listbox = tk.Listbox(left_frame, width=30)
        self.section_listbox.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.section_listbox.bind('<<ListboxSelect>>', self.on_section_select)

        add_section_frame = ttk.Frame(left_frame)
        add_section_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.new_section_entry = tk.Text(add_section_frame, height=3, width=30, wrap=tk.WORD)
        self.new_section_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(add_section_frame, text="Add Section", command=self.add_section).pack(side=tk.RIGHT)
        ttk.Button(add_section_frame, text="Remove Section", command=self.remove_section).pack(side=tk.RIGHT)

        # Right side: Question management
        right_frame = ttk.Frame(self)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.question_listbox = tk.Listbox(right_frame)
        self.question_listbox.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        button_frame = ttk.Frame(right_frame)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(button_frame, text="Add Question", command=self.add_question).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Edit Question", command=self.edit_question).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Remove Question", command=self.remove_question).pack(side=tk.LEFT)

    def load_questions(self):
        try:
            with open('guided_questions.json', 'r') as f:
                self.app.guided_questions = json.load(f)
        except FileNotFoundError:
            messagebox.showerror("Error", "Questions file not found. Creating a new one.")
            self.app.guided_questions = {}
        except json.JSONDecodeError:
            messagebox.showerror("Error", "Invalid JSON in questions file.")
            self.app.guided_questions = {}

    def populate_sections(self):
        self.section_listbox.delete(0, tk.END)
        for section in self.app.guided_questions.keys():
            self.section_listbox.insert(tk.END, section)
        
        # Automatically select the first section, if available
        if self.section_listbox.size() > 0:
            self.section_listbox.selection_set(0)
            self.on_section_select(None)  # Populate questions for the first section

    def on_section_select(self, event):
        self.populate_questions()

    def populate_questions(self):
        selected = self.section_listbox.curselection()
        if not selected:
            return
        section = self.section_listbox.get(selected[0])
        
        # Safely handle the missing 'questions' key
        if 'questions' not in self.app.guided_questions[section]:
            self.app.guided_questions[section]['questions'] = []

        self.question_listbox.delete(0, tk.END)
        for question in self.app.guided_questions[section]['questions']:
            # Check for missing 'question' key
            if 'question' in question:
                self.question_listbox.insert(tk.END, question['question'])
            else:
                self.question_listbox.insert(tk.END, "<No question text>")

    def add_section(self):
        new_section = self.new_section_entry.get('1.0', tk.END).strip()
        if new_section and new_section not in self.app.guided_questions:
            self.app.guided_questions[new_section] = {'type': 'section', 'questions': []}
            self.populate_sections()
            self.new_section_entry.delete('1.0', tk.END)
            self.save_questions()


    def remove_section(self):
        selected_section = self.section_listbox.curselection()
        if not selected_section:
            messagebox.showwarning("Warning", "Please select a section to remove.")
            return
        
        section = self.section_listbox.get(selected_section[0])
        if messagebox.askyesno("Confirm", f"Are you sure you want to remove the section '{section}'?"):
            del self.app.guided_questions[section]
            self.populate_sections()
            self.populate_questions()
            self.save_questions()

    def add_question(self):
        selected = self.section_listbox.curselection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a section first.")
            return
        
        section = self.section_listbox.get(selected[0])
        question_types = ['checkbox', 'yesno', 'multiple', 'open']
        
        # Create a new window for adding a question
        add_question_window = tk.Toplevel(self)
        add_question_window.title("Add Question")
        add_question_window.geometry("300x200")
        
        tk.Label(add_question_window, text="Select Question Type:").pack(pady=5)
        question_type_var = tk.StringVar()
        question_type_combobox = ttk.Combobox(add_question_window, textvariable=question_type_var, values=question_types)
        question_type_combobox.pack(pady=5)
        
        tk.Label(add_question_window, text="Enter Question:").pack(pady=5)
        question_entry = ttk.Entry(add_question_window)
        question_entry.pack(pady=5)
        
        def save_question():
            question_type = question_type_var.get()
            if question_type not in question_types:
                messagebox.showwarning("Warning", "Invalid question type.")
                return
            
            new_question = {
                "question": question_entry.get().strip(),
                "type": question_type
            }
            
            if question_type in ['checkbox', 'multiple']:
                options = []
                while True:
                    option = simpledialog.askstring("Option", "Enter an option (or cancel to finish):")
                    if option:
                        options.append(option)
                    else:
                        break
                new_question['options'] = options
            
            self.app.guided_questions[section]['questions'].append(new_question)
            self.populate_questions()
            self.save_questions()
            add_question_window.destroy()
        
        ttk.Button(add_question_window, text="Save", command=save_question).pack(pady=10)

    def edit_question(self):
        selected_section_index = self.section_listbox.curselection()
        selected_question_index = self.question_listbox.curselection()

        if not selected_section_index or not selected_question_index:
            messagebox.showwarning("Warning", "Please select a section and a question to edit.")
            return

        # Get selected section and question
        section = self.section_listbox.get(selected_section_index[0])
        question_index = selected_question_index[0]
        question_data = self.app.guided_questions[section]['questions'][question_index]

        # Create a window to edit the question
        edit_question_window = tk.Toplevel(self)
        edit_question_window.title("Edit Question")
        edit_question_window.geometry("300x200")

        tk.Label(edit_question_window, text="Edit Question:").pack(pady=5)
        question_entry = ttk.Entry(edit_question_window)
        question_entry.insert(0, question_data['question'])
        question_entry.pack(pady=5)

        def save_edited_question():
            edited_question_text = question_entry.get().strip()
            if not edited_question_text:
                messagebox.showwarning("Warning", "Question text cannot be empty.")
                return

            question_data['question'] = edited_question_text

            # Handle options for 'checkbox' and 'multiple' question types
            if question_data['type'] in ['checkbox', 'multiple']:
                options = question_data.get('options', [])
                for i, option in enumerate(options):
                    new_option = simpledialog.askstring("Edit Option", f"Option {i + 1}:", initialvalue=option)
                    if new_option:
                        options[i] = new_option
                question_data['options'] = options

            self.populate_questions()
            self.save_questions()
            edit_question_window.destroy()

        ttk.Button(edit_question_window, text="Save", command=save_edited_question).pack(pady=10)

    def remove_question(self):
        selected_section_index = self.section_listbox.curselection()
        selected_question_index = self.question_listbox.curselection()

        if not selected_section_index or not selected_question_index:
            messagebox.showwarning("Warning", "Please select a section and a question to remove.")
            return

        section = self.section_listbox.get(selected_section_index[0])
        question_index = selected_question_index[0]

        if messagebox.askyesno("Confirm", "Are you sure you want to remove this question?"):
            del self.app.guided_questions[section]['questions'][question_index]
            self.populate_questions()
            self.save_questions()


        
class AdminSection:
    def __init__(self, master, app):
        self.master = master
        self.app = app
        self.create_widgets()

    def create_widgets(self):
        self.password_entry = ttk.Entry(self.master, show="*")
        self.password_entry.pack(pady=10)
        ttk.Button(self.master, text="Login", command=self.login).pack()

    def login(self):
        if self.app.verify_password(self.password_entry.get()):
            self.show_admin_panel()
        else:
            messagebox.showerror("Error", "Incorrect password")

    def show_admin_panel(self):
        for widget in self.master.winfo_children():
            widget.destroy()

        ttk.Button(self.master, text="Manage Questions", command=self.manage_questions).pack(pady=10)
        ttk.Button(self.master, text="Change Password", command=self.change_password).pack(pady=10)
        ttk.Button(self.master, text="Save Changes", command=self.save_changes).pack(pady=10)

    def manage_questions(self):
        QuestionManager(self.master, self.app)

    def change_password(self):
        old_password = simpledialog.askstring("Input", "Enter current password:", show="*")
        if self.app.verify_password(old_password):
            new_password = simpledialog.askstring("Input", "Enter new password:", show="*")
            if new_password:
                confirm_password = simpledialog.askstring("Input", "Confirm new password:", show="*")
                if new_password == confirm_password:
                    self.app.save_password(new_password)
                    self.app.load_password()  # Reload the password after saving
                    messagebox.showinfo("Success", "Password changed successfully!")
                else:
                    messagebox.showerror("Error", "Passwords do not match")
        else:
            messagebox.showerror("Error", "Incorrect current password")

    def save_changes(self):
        self.app.save_questions()
        messagebox.showinfo("Success", "Changes saved successfully!")
        
class LLMPlayground:
    def __init__(self, master):
        self.master = master
        master.title("LLM Playground")
        master.geometry("1200x800")
        
        self.guided_questions = {}
        self.load_questions()
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
        self.admin_password_hash = None
        self.load_password()
        
    def save_password(self, password):
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        with open('admin_password.hash', 'wb') as f:
            f.write(hashed)

    def load_password(self):
        try:
            with open('admin_password.hash', 'rb') as f:
                self.admin_password_hash = f.read()
        except FileNotFoundError:
            # If the file doesn't exist, set a default password
            default_password = "admin_password"
            self.save_password(default_password)
            self.load_password()

    def verify_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.admin_password_hash)
        
    def load_questions(self):
        try:
            with open('guided_questions.json', 'r') as f:
                self.guided_questions = json.load(f)
        except FileNotFoundError:
            # If the file doesn't exist, use default questions
            self.guided_questions = {
                "Fields": {
                    "type": "checkbox",
                    "options": ["EMC", "Safety", "Wireless", "Telecom/PSTN", "Materials", "Energy", "Packaging", "Cybersecurity", "US Federal", "Others"]
                },
                "Impacts": {
                    "type": "checkbox",
                    "options": ["Certification / DOC/ Registration", "New/ Revision", "Regulatory Filing", "Design Change", "Component impact", "Cost impact", "Factory inspection", "Label – New/ Revised Packaging Label", "Logistics", "Product Label", "Product Documentation/Web", "Producer Responsibility/ EDPs", "RQA Revision /Creation", "Specification Revision/ Creation", "Supply Chain", "Testing", "Trade Compliance", "Configuration Restriction", "Sales Operation", "Services (Product/Operation/Logistics)", "Annual Report", "TBD"]
                },
                # ... add other default questions here ...
            }
        
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
        ttk.Button(sidebar, text="Admin Section", command=self.open_admin_section).pack(pady=5, fill='x')
        
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

    def open_admin_section(self):
        admin_window = tk.Toplevel(self.master)
        admin_window.title("Admin Section")
        AdminSection(admin_window, self)
    
    def guided_prompt_creation(self):
        print("Starting guided prompt creation...")
        answers = {}

        for section, data in self.guided_questions.items():
            for question in data.get('questions', []):  # Use get to handle missing 'questions' key
                if question['type'] == 'checkbox':
                    dialog = GuidedQuestionDialog(self.master, section, question)
                    self.master.wait_window(dialog)
                    if dialog.result:
                        answers[section] = [option for option, var in dialog.result if var.get()]
                
                elif question['type'] == 'yesno':
                    answer = messagebox.askyesno(section, question.get('question', "Yes/No Question"))
                    answers[section] = "Yes" if answer else "No"
                
                elif question['type'] == 'multiple':
                    if messagebox.askyesno(section, question.get('question', "Multiple Choice Question")):
                        dialog = GuidedQuestionDialog(self.master, f"{section} options", question)
                        self.master.wait_window(dialog)
                        if dialog.result:
                            answers[section] = [option for option, var in dialog.result if var.get()]
                    else:
                        answers[section] = "No"
                
                elif question['type'] == 'open':
                    dialog = GuidedQuestionDialog(self.master, section, question)
                    self.master.wait_window(dialog)
                    answer = dialog.result
                    if answer:
                        answers[section] = answer

        # Construct the suggested prompt
        suggested_prompt = "Please summarize the attached document with the following considerations:\n\n"
        for section, answer in answers.items():
            if isinstance(answer, list):
                suggested_prompt += f"{section}: {', '.join(answer)}\n"
            else:
                suggested_prompt += f"{section}: {answer}\n"

        suggested_prompt += "\nPlease provide a comprehensive summary for a bulletin based on these factors. Pretend that you are a regulatory engineer whose job is to interpret this document into an internal regulatory bulletin for engineers to follow some important compliance guidance. Do not focus on punishments or penalties. Please provide the summary with all the following sections, and all of them should be filled in with corresponding information:\n"
        suggested_prompt += "1) Program Requirements Summary\n2) Regulation Publication Date\n3) Enforcement Date\n4) Enforcement based on\n5) Compliance Checkpoint\n6) Regulation Status\n7) Current process\n8) Changes from current process\n9) Key Details – Legislation Requirement\n10) Requirement\n11) Dependency\n12) Details of Requirement\n13) Wireless Technology Scope\n14) Detail Requirements\n"

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

    def display_file_briefing(self, file_content, guided_prompt):
        briefing = f"File Content Preview:\n{file_content[:500]}...\n\nGuided Prompt:\n{guided_prompt}"
        self.conversations[self.current_conversation].append({"role": "system", "content": briefing})
        self.update_chat_display()

    def send_message(self):
        if self.is_generating:
            return
        
        user_input = self.user_input.get()
        if not user_input and not self.attached_file_content:
            return

        # Ensure there is a current conversation
        if self.current_conversation is None:
            self.new_chat()

        if self.attached_file_content:
            suggested_prompt = self.guided_prompt_creation()
            if suggested_prompt:
                user_input += suggested_prompt
                
            # Ask if the user wants an AI-generated summary
            if messagebox.askyesno("AI Summary", "Do you want an AI-generated summary of the attached file?"):
                threading.Thread(target=self.get_model_response, args=(self.model_combobox.get(), user_input)).start()
            else:
                self.display_file_briefing(self.attached_file_content, user_input)
        else:
            # Normal message without attachment
            self.conversations[self.current_conversation].append({"role": "user", "content": user_input})
            self.update_chat_display()
            threading.Thread(target=self.get_model_response, args=(self.model_combobox.get(), user_input)).start()

        self.user_input.delete(0, tk.END)
        self.attached_file_content = None  # Reset after sending


    def save_questions(self):
        with open('guided_questions.json', 'w') as f:
            json.dump(self.guided_questions, f)

    def load_questions(self):
        try:
            with open('guided_questions.json', 'r') as f:
                self.guided_questions = json.load(f)
        except FileNotFoundError:
            # If the file doesn't exist, use default questions
            self.guided_questions = {
                "Fields": {
                    "type": "checkbox",
                    "options": ["EMC", "Safety", "Wireless", "Telecom/PSTN", "Materials", "Energy", "Packaging", "Cybersecurity", "US Federal", "Others"]
                },
                "Impacts": {
                    "type": "checkbox",
                    "options": ["Certification / DOC/ Registration", "New/ Revision", "Regulatory Filing", "Design Change", "Component impact", "Cost impact", "Factory inspection", "Label – New/ Revised Packaging Label", "Logistics", "Product Label", "Product Documentation/Web", "Producer Responsibility/ EDPs", "RQA Revision /Creation", "Specification Revision/ Creation", "Supply Chain", "Testing", "Trade Compliance", "Configuration Restriction", "Sales Operation", "Services (Product/Operation/Logistics)", "Annual Report", "TBD"]
                },
                # ... add other default questions here ...
            }

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