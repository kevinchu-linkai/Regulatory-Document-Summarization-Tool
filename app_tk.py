import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox, simpledialog
import requests
import json
import bcrypt
import os
import pickle
import pandas as pd
from fuzzywuzzy import process
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import docx2txt
import PyPDF2
import csv
import io
import tiktoken
import re
import concurrent.futures
from openai import OpenAI
import httpx
import threading
from dotenv import load_dotenv

load_dotenv('.env', override=True)

http_client=httpx.Client(verify=False)
client = OpenAI(
    base_url='https://opensource-challenger-api.prdlvgpu1.aiaccel.dell.com/v1',
    http_client=http_client,
    api_key=os.environ["CHALLENGER_GENAI_API_KEY"]
)

streaming = True
max_output_tokens = 8000

class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

class QuestionDialog(tk.Toplevel):
    def __init__(self, parent, title, question_data=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("800x600")
        self.minsize(800, 600)
        self.follow_up_questions = question_data.get('follow_up', []) if question_data else []
        self.question_data = question_data or {}
        self.result = None
        self.parent = parent
        self.scrollable_frame = ScrollableFrame(self)
        self.scrollable_frame.pack(fill="both", expand=True)
        
        self.create_widgets()
        self.update_follow_up_button()
        
    def create_widgets(self):
        # Question type
        ttk.Label(self.scrollable_frame.scrollable_frame, text="Question Type:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.type_var = tk.StringVar(value=self.question_data.get('type', 'checkbox'))
        type_combo = ttk.Combobox(self.scrollable_frame.scrollable_frame, textvariable=self.type_var, values=['checkbox', 'yesno', 'multiple', 'open'])
        type_combo.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        type_combo.bind("<<ComboboxSelected>>", self.on_type_change)
        
        # Question text
        ttk.Label(self.scrollable_frame.scrollable_frame, text="Question:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.question_entry = ttk.Entry(self.scrollable_frame.scrollable_frame, width=40)
        self.question_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.question_entry.insert(0, self.question_data.get('question', ''))
        
        # Options frame (for checkbox and multiple)
        self.options_frame = ttk.LabelFrame(self.scrollable_frame.scrollable_frame, text="Options")
        self.options_frame.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
        
        # Add option button
        self.add_option_button = ttk.Button(self.scrollable_frame.scrollable_frame, text="Add Option", command=self.add_option)
        self.add_option_button.grid(row=3, column=0, columnspan=2, padx=5, pady=5)
        
        # Follow-up questions
        self.follow_up_frame = ttk.LabelFrame(self.scrollable_frame.scrollable_frame, text="Follow-up Questions")
        self.follow_up_frame.grid(row=5, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")

        self.follow_up_button = ttk.Button(self.scrollable_frame.scrollable_frame, text="Add Follow-up Question", command=self.add_follow_up_question)
        self.follow_up_button.grid(row=6, column=0, columnspan=2, padx=5, pady=5)
        
        # Save button
        self.save_button = ttk.Button(self.scrollable_frame.scrollable_frame, text="Save", command=self.save)
        self.save_button.grid(row=7, column=0, columnspan=2, padx=5, pady=5)
        
        self.option_entries = []
        if 'options' in self.question_data:
            for option in self.question_data['options']:
                self.add_option(option)
        
        self.on_type_change()
        self.update_follow_up_display()
      
    def add_follow_up_question(self):
        follow_up_dialog = QuestionDialog(self, "Add Follow-up Question")
        self.wait_window(follow_up_dialog)
        if follow_up_dialog.result:
            condition = simpledialog.askstring("Follow-up Condition", "Enter the condition for this follow-up question (yes/no):")
            if condition in ['yes', 'no']:
                follow_up_dialog.result['condition'] = condition
                self.follow_up_questions.append(follow_up_dialog.result)
                self.update_follow_up_display()
                self.save_follow_up_questions()  # Save changes immediately
            else:
                messagebox.showerror("Invalid Condition", "Please enter either 'yes' or 'no' as the condition.")
        self.update_geometry()

    def save_follow_up_questions(self):
        if isinstance(self.parent, QuestionManager):
            self.parent.save_follow_up_questions(self.question_data, self.follow_up_questions)
        else:
            print("Warning: Unable to save follow-up questions. Parent is not QuestionManager.")

    def update_follow_up_button(self):
        if self.type_var.get() == 'yesno':
            self.follow_up_button.grid()
        else:
            self.follow_up_button.grid_remove()

    def update_follow_up_display(self):
        for widget in self.follow_up_frame.winfo_children():
            widget.destroy()
        for i, question in enumerate(self.follow_up_questions):
            ttk.Label(self.follow_up_frame, text=f"{i+1}. {question['question']}").grid(row=i, column=0, sticky="w")
            ttk.Button(self.follow_up_frame, text="Edit", command=lambda q=question: self.edit_follow_up(q)).grid(row=i, column=1)
            ttk.Button(self.follow_up_frame, text="Remove", command=lambda q=question: self.remove_follow_up(q)).grid(row=i, column=2)

    def edit_follow_up(self, question):
        index = self.follow_up_questions.index(question)
        follow_up_dialog = QuestionDialog(self, "Edit Follow-up Question", question)
        self.wait_window(follow_up_dialog)
        if follow_up_dialog.result:
            self.follow_up_questions[index] = follow_up_dialog.result
            self.update_follow_up_display()
        self.update_geometry()

    def remove_follow_up(self, question):
        self.follow_up_questions.remove(question)
        self.update_follow_up_display()
        self.update_geometry()
        
    def on_type_change(self, event=None):
        question_type = self.type_var.get()
        if question_type in ['checkbox', 'multiple']:
            self.options_frame.grid()
            self.add_option_button.grid()
        else:
            self.options_frame.grid_remove()
            self.add_option_button.grid_remove()
        self.update_follow_up_button()
        
    def add_option(self, option_text=''):
        row = len(self.option_entries)
        entry = ttk.Entry(self.options_frame, width=30)
        entry.grid(row=row, column=0, padx=5, pady=2, sticky="ew")
        entry.insert(0, option_text)
        
        remove_btn = ttk.Button(self.options_frame, text="X", width=2, 
                                command=lambda: self.remove_option(entry, remove_btn))
        remove_btn.grid(row=row, column=1, padx=2, pady=2)
        
        self.option_entries.append((entry, remove_btn))
        self.update_geometry()
        
    def remove_option(self, entry, button):
        entry.destroy()
        button.destroy()
        self.option_entries.remove((entry, button))
        self.options_frame.grid_columnconfigure(0, weight=1)
        self.update_geometry()
        
    def save(self):
        question_type = self.type_var.get()
        question_text = self.question_entry.get().strip()
        
        if not question_text:
            messagebox.showwarning("Warning", "Question text cannot be empty.")
            return
        
        self.result = {
            'type': question_type,
            'question': question_text
        }
        
        if question_type in ['checkbox', 'multiple']:
            options = [entry.get().strip() for entry, _ in self.option_entries if entry.get().strip()]
            if len(options) < 2:
                messagebox.showwarning("Warning", "Please add at least two options.")
                return
            self.result['options'] = options
        
        if self.follow_up_questions:
            self.result['follow_up'] = self.follow_up_questions
        
        self.destroy()

    def update_follow_up_button(self):
        if self.type_var.get() == 'yesno':
            self.follow_up_button.grid()
        else:
            self.follow_up_button.grid_remove()

    def update_geometry(self):
        self.scrollable_frame.scrollable_frame.update_idletasks()
        self.geometry(f"800x{min(600, self.scrollable_frame.scrollable_frame.winfo_reqheight() + 50)}")

class GuidedQuestionDialog(tk.Toplevel):
    def __init__(self, parent, title, question_data):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x300")
        self.minsize(400, 300)
        self.result = None
        self.question_data = question_data
        
        self.scrollable_frame = ScrollableFrame(self)
        self.scrollable_frame.pack(fill="both", expand=True)
        
        self.create_dialog()

    def create_dialog(self):
        question_type = self.question_data['type']
        question_text = self.question_data['question']
        
        label = tk.Label(self.scrollable_frame.scrollable_frame, text=question_text, wraplength=380, justify="left")
        label.pack(anchor="w", padx=10, pady=5)
        
        if question_type == 'checkbox':
            self.create_checkbox_dialog(self.question_data['options'])
        elif question_type == 'yesno':
            self.create_yesno_dialog()
        elif question_type == 'multiple':
            self.create_multiple_dialog(self.question_data['options'])
        elif question_type == 'open':
            self.create_open_dialog()

        self.add_ok_button()

    def create_checkbox_dialog(self, options):
        self.result = []
        for option in options:
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(self.scrollable_frame.scrollable_frame, text=option, variable=var)
            cb.pack(anchor="w", padx=10, pady=5)
            self.result.append((option, var))

    def create_yesno_dialog(self):
        self.result = tk.StringVar(value="No")
        ttk.Radiobutton(self.scrollable_frame.scrollable_frame, text="Yes", variable=self.result, value="Yes").pack(anchor="w", padx=10, pady=5)
        ttk.Radiobutton(self.scrollable_frame.scrollable_frame, text="No", variable=self.result, value="No").pack(anchor="w", padx=10, pady=5)
        ttk.Radiobutton(self.scrollable_frame.scrollable_frame, text="TBD", variable=self.result, value="TBD").pack(anchor="w", padx=10, pady=5)

    def create_multiple_dialog(self, options):
        self.result = []
        for option in options:
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(self.scrollable_frame.scrollable_frame, text=option, variable=var)
            cb.pack(anchor="w", padx=10, pady=5)
            self.result.append((option, var))

    def create_open_dialog(self):
        self.result = tk.Text(self.scrollable_frame.scrollable_frame, height=4, width=40, wrap=tk.WORD)
        self.result.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

    def add_ok_button(self):
        ttk.Button(self.scrollable_frame.scrollable_frame, text="OK", command=self.on_ok).pack(pady=10)

    def on_ok(self):
        if isinstance(self.result, tk.Text):
            self.result = self.result.get("1.0", tk.END).strip()
        self.destroy()

    def adjust_window_size(self):
        self.update_idletasks()
        width = max(400, min(self.winfo_reqwidth(), 800))
        height = max(200, min(self.winfo_reqheight(), 600))
        self.geometry(f"{width}x{height}")
        
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
        self.geometry("800x600")
        self.minsize(800, 600)
        self.current_section = None
        self.create_widgets()
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
            self.on_section_select(None)

    def on_section_select(self, event):
        selected = self.section_listbox.curselection()
        if selected:
            self.current_section = self.section_listbox.get(selected[0])
            self.populate_questions()

    def add_section(self):
        new_section = self.new_section_entry.get('1.0', tk.END).strip()
        if new_section and new_section not in self.app.guided_questions:
            self.app.guided_questions[new_section] = {'type': 'section', 'questions': []}
            self.populate_sections()
            self.new_section_entry.delete('1.0', tk.END)
            self.app.save_questions()

    def remove_section(self):
        if not self.current_section:
            messagebox.showwarning("Warning", "Please select a section to remove.")
            return
        
        if messagebox.askyesno("Confirm", f"Are you sure you want to remove the section '{self.current_section}'?"):
            del self.app.guided_questions[self.current_section]
            self.current_section = None
            self.populate_sections()
            self.populate_questions()
            self.app.save_questions()

    def populate_questions(self):
        self.question_listbox.delete(0, tk.END)
        if self.current_section and 'questions' in self.app.guided_questions[self.current_section]:
            for question in self.app.guided_questions[self.current_section]['questions']:
                self.question_listbox.insert(tk.END, question['question'])

    def add_question(self):
        if not self.current_section:
            messagebox.showwarning("Warning", "Please select a section first.")
            return
        
        dialog = QuestionDialog(self, "Add Question")
        self.wait_window(dialog)
        
        if dialog.result:
            if 'questions' not in self.app.guided_questions[self.current_section]:
                self.app.guided_questions[self.current_section]['questions'] = []
            self.app.guided_questions[self.current_section]['questions'].append(dialog.result)
            self.populate_questions()
            self.save_questions()

    def edit_question(self):
        if not self.current_section:
            messagebox.showwarning("Warning", "Please select a section first.")
            return

        selected_question_index = self.question_listbox.curselection()
        if not selected_question_index:
            messagebox.showwarning("Warning", "Please select a question to edit.")
            return

        question_index = selected_question_index[0]
        question_data = self.app.guided_questions[self.current_section]['questions'][question_index]

        dialog = QuestionDialog(self, "Edit Question", question_data)
        self.wait_window(dialog)
        
        if dialog.result:
            self.app.guided_questions[self.current_section]['questions'][question_index] = dialog.result
            self.populate_questions()
            self.save_questions()

    def save_follow_up_questions(self, question_data, follow_up_questions):
        for section_name, section in self.app.guided_questions.items():
            for i, question in enumerate(section.get('questions', [])):
                if question == question_data:
                    if 'follow_up' not in question:
                        question['follow_up'] = []
                    question['follow_up'] = follow_up_questions
                    self.app.guided_questions[section_name]['questions'][i] = question
                    self.save_questions()
                    messagebox.showinfo("Success", "Follow-up questions saved successfully!")
                    return
        print("Warning: Question not found. Follow-up questions not saved.")

    def save_questions(self):
        with open('guided_questions.json', 'w') as f:
            json.dump(self.app.guided_questions, f, indent=2)
        print("Questions saved to guided_questions.json") 

    def remove_question(self):
        if not self.current_section:
            messagebox.showwarning("Warning", "Please select a section first.")
            return

        selected_question_index = self.question_listbox.curselection()
        if not selected_question_index:
            messagebox.showwarning("Warning", "Please select a question to remove.")
            return

        question_index = selected_question_index[0]

        if messagebox.askyesno("Confirm", "Are you sure you want to remove this question?"):
            del self.app.guided_questions[self.current_section]['questions'][question_index]
            self.populate_questions()
            self.app.save_questions()
        
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
        
class LLMPlayground:
    def __init__(self, master):
        self.master = master
        master.title("Regulatory Bulletin Assistant")
        master.geometry("1200x800")
        self.font_size = tk.IntVar(value=12)
        self.max_file_size = 5 * 1024 * 1024  # 5 MB limit, adjust as needed
        self.keywords_df = pd.read_csv('keyword_extraction.csv')
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
        self.load_api_key()
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        self.create_widgets()
        self.apply_style()
        self.admin_password_hash = None
        self.load_password()
        
    def load_api_key(self):
        load_dotenv('.env', override=True)
        self.api_key = os.environ.get("CHALLENGER_GENAI_API_KEY")
        if not self.api_key:
            raise ValueError("API key not found. Please set CHALLENGER_GENAI_API_KEY in your .env file.")

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

        # Add font size slider
        ttk.Label(sidebar, text="Font Size").pack(pady=5)
        font_size_slider = ttk.Scale(sidebar, from_=12, to=20, orient='horizontal', variable=self.font_size, command=self.update_font_size)
        font_size_slider.pack(pady=5, padx=5, fill='x')

        ttk.Label(sidebar, text="Your conversations").pack(pady=5)
        self.conversation_listbox = tk.Listbox(sidebar)
        self.conversation_listbox.pack(pady=5, padx=5, fill='x')
        self.conversation_listbox.bind('<<ListboxSelect>>', self.on_conversation_select)

        ttk.Label(sidebar, text="Temperature").pack(pady=5)
        self.temperature_scale = ttk.Scale(sidebar, from_=0, to=1, orient='horizontal')
        self.temperature_scale.set(0.4)
        self.temperature_scale.pack(pady=5, padx=5, fill='x')

        ttk.Label(sidebar, text="Max Tokens").pack(pady=5)
        self.max_tokens_entry = ttk.Entry(sidebar)
        self.max_tokens_entry.insert(0, "8192")
        self.max_tokens_entry.pack(pady=5, padx=5, fill='x')

        ttk.Button(sidebar, text="Upload Context for RAG", command=self.upload_context_for_rag).pack(pady=5, fill='x')

        # Chat area widgets
        self.chat_display = scrolledtext.ScrolledText(chat_area, state='disabled', wrap=tk.WORD, font=("TkDefaultFont", self.font_size.get()))
        self.chat_display.pack(pady=10, fill='both', expand=True)

        # Create input frame
        input_frame = ttk.Frame(chat_area)
        input_frame.pack(fill='x', pady=10)

        self.user_input = ttk.Entry(input_frame, font=("TkDefaultFont", self.font_size.get()))
        self.user_input.pack(side='left', fill='x', expand=True)

        ttk.Button(input_frame, text="Attach File", command=self.attach_file).pack(side='left', padx=5)
        ttk.Button(input_frame, text="Send", command=self.send_message).pack(side='left')

        # Configure text tags
        self.chat_display.tag_configure('user', foreground='blue')
        self.chat_display.tag_configure('user_message', foreground='black')
        self.chat_display.tag_configure('assistant', foreground='green')
        self.chat_display.tag_configure('assistant_message', foreground='black')

        # Set the model
        self.model = "llama-3-8b-instruct"
        print(f"Using model: {self.model}")
        
    def apply_style(self):
        style = ttk.Style()
        style.theme_use('clam')

        style.configure('.', background='#f0f0f0', foreground='#333333')
        style.configure('TButton', background='#0672CB', foreground='white')
        style.map('TButton', background=[('active', '#0C3244')])
        style.configure('TEntry', fieldbackground='white')
        style.configure('TCombobox', fieldbackground='white')
        style.configure('TScale', background='#0672CB')

        default_font = ('Aldhabi', 16)
        heading_font = ('Aldhabi', 18, 'bold')
        
        style.configure('.', font=default_font)
        style.configure('TButton', font=default_font)
        style.configure('TLabel', font=heading_font)

        self.chat_display.configure(font=default_font, background='white', foreground='#333333')
        self.conversation_listbox.configure(font=default_font, background='white', foreground='#333333')

    def update_font_size(self, event=None):
        new_size = self.font_size.get()
        self.chat_display.configure(font=("TkDefaultFont", new_size))
        self.user_input.configure(font=("TkDefaultFont", new_size))
        # Update font size for other widgets as needed

    def open_admin_section(self):
        admin_window = tk.Toplevel(self.master)
        admin_window.title("Admin Section")
        AdminSection(admin_window, self)
    
    def guided_prompt_creation(self):
        print("Starting guided prompt creation...")
        answers = {}

        for section, data in self.guided_questions.items():
            section_answers = []
            for question in data.get('questions', []):
                question_text = question.get('question', '')
                question_type = question.get('type', '')
                
                if question_type == 'checkbox':
                    dialog = GuidedQuestionDialog(self.master, question_text, question)
                    self.master.wait_window(dialog)
                    if dialog.result:
                        selected_options = [option for option, var in dialog.result if var.get()]
                        section_answers.append(f"{question_text}: {', '.join(selected_options)}")
                
                elif question_type == 'yesno':
                    dialog = GuidedQuestionDialog(self.master, question_text, question)
                    self.master.wait_window(dialog)
                    if dialog.result:
                        answer = dialog.result.get()
                        section_answers.append(f"{question_text}: {answer}")
                        
                        # Handle follow-up questions
                        for follow_up in question.get('follow_up', []):
                            if follow_up['condition'] == answer.lower():
                                follow_up_answer = self.process_follow_up_question(follow_up)
                                if follow_up_answer:
                                    section_answers.append(follow_up_answer)
                
                elif question_type == 'multiple':
                    dialog = GuidedQuestionDialog(self.master, question_text, question)
                    self.master.wait_window(dialog)
                    if dialog.result:
                        selected_options = [option for option, var in dialog.result if var.get()]
                        section_answers.append(f"{question_text}: {', '.join(selected_options)}")
                
                elif question_type == 'open':
                    dialog = GuidedQuestionDialog(self.master, question_text, question)
                    self.master.wait_window(dialog)
                    if dialog.result:
                        section_answers.append(f"{question_text}: {dialog.result}")

            if section_answers:
                answers[section] = section_answers

        # Construct the suggested prompt
        suggested_prompt = "Please summarize the attached document with the following considerations:\n\n"
        for section, section_answers in answers.items():
            suggested_prompt += f"{section}:\n"
            for answer in section_answers:
                suggested_prompt += f"- {answer}\n"
            suggested_prompt += "\n"

        suggested_prompt += "\nPlease provide a comprehensive summary for a bulletin based on these factors. Pretend that you are a regulatory engineer whose job is to interpret this document into an internal regulatory bulletin for engineers to follow some important compliance guidance. Do not focus on punishments or penalties. Please provide the summary with all the following sections, and all of them should be filled in with corresponding information:\n"
        suggested_prompt += "1) Program Requirements Summary: a 2-3 sentence, brief summary of the regulation.\n" + \
                            "2) Regulation Publication Date: the date the regulation was published. If regulation has not been published, leave this blank.\n" + \
                            "3) Enforcement Date: This is the effective date of the regulation.\n" + \
                            "4) Enforcement based on: Type of enforcement\n" + \
                            "5) Compliance Checkpoint: How is regulation enforced upon entry?\n" + \
                            "6) Regulation Status: Type of Regulation Status\n" + \
                            "7) What is current process: If a regulation revision, this will be a 2-3 sentence summary of the current process, if it is a new regulation, note that it is new\n" + \
                            "8) What has changed from current process:  2-3 sentence summary of what is changing from existing regulation process.  This section is what is used for Bulletin email summaries. Character limit has been increased to 1000. Must ensure Summary in properties reflects same as Bulletin\n" + \
                            "9) Key Details – Legislation Requirement: This section is the regulation requirements. What is needed to reach compliance.\n" + \
                            "10) Requirement: Frequently used Requirements are listed in the table template, add additional requirements as required, and delete those not relevant.\n" + \
                            "11) Dependency: Is the requirement dependent on another requirement in the table? If so, list the requirement that must be completed to meet the requirement.\n" + \
                            "12) Details of Requirement: High level explanation of the regulatory requirement\n" + \
                            "13) Wireless Technology Scope: For Wireless Programs only, leave blank if not related\n" + \
                            "14) Detail Requirements: This is details of Regulation.  May include some tables and technical detail copied from regulation.  Should not, however be a straight copy/paste.\n"

        print(f"Suggested prompt: {suggested_prompt}")
        return suggested_prompt

    def process_follow_up_question(self, follow_up):
        question_text = follow_up.get('question', '')
        question_type = follow_up.get('type', '')
        
        if question_type == 'checkbox':
            dialog = GuidedQuestionDialog(self.master, question_text, follow_up)
            self.master.wait_window(dialog)
            if dialog.result:
                selected_options = [option for option, var in dialog.result if var.get()]
                return f"{question_text}: {', '.join(selected_options)}"
        
        elif question_type == 'yesno':
            dialog = GuidedQuestionDialog(self.master, question_text, follow_up)
            self.master.wait_window(dialog)
            if dialog.result:
                return f"{question_text}: {dialog.result.get()}"
        
        elif question_type == 'multiple':
            dialog = GuidedQuestionDialog(self.master, question_text, follow_up)
            self.master.wait_window(dialog)
            if dialog.result:
                selected_options = [option for option, var in dialog.result if var.get()]
                return f"{question_text}: {', '.join(selected_options)}"
        
        elif question_type == 'open':
            dialog = GuidedQuestionDialog(self.master, question_text, follow_up)
            self.master.wait_window(dialog)
            if dialog.result:
                return f"{question_text}: {dialog.result}"
        
        return None

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
            try:
                # Check file size
                file_size = os.path.getsize(file_path)
                if file_size > self.max_file_size:
                    raise ValueError(f"File size ({file_size / (1024 * 1024):.2f} MB) exceeds the maximum allowed size ({self.max_file_size / (1024 * 1024)} MB)")

                self.attached_file_content = self.read_file_content(file_path)
                file_name = os.path.basename(file_path)
                self.user_input.insert(tk.END, f" [Attached: {file_name}]")
            except ValueError as e:
                error_message = str(e)
                print(error_message)
                messagebox.showerror("File Attachment Error", error_message)
            except Exception as e:
                error_message = f"Error attaching file: {str(e)}"
                print(error_message)
                messagebox.showerror("File Attachment Error", error_message)

    def read_file_content(self, file_path):
        _, file_extension = os.path.splitext(file_path)
        
        # Check file size again before reading
        file_size = os.path.getsize(file_path)
        if file_size > self.max_file_size:
            raise ValueError(f"File size ({file_size / (1024 * 1024):.2f} MB) exceeds the maximum allowed size ({self.max_file_size / (1024 * 1024)} MB)")

        if file_extension == '.txt':
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        elif file_extension == '.docx':
            content = docx2txt.process(file_path)
            print(f"Docx content length: {len(content)}")
            return content
        elif file_extension == '.pdf':
            try:
                with open(file_path, 'rb') as file:
                    pdf_reader = PyPDF2.PdfReader(file)
                    content = []
                    for page in pdf_reader.pages:
                        content.append(page.extract_text())
                    return ' '.join(content)
            except Exception as e:
                print(f"Error reading PDF: {str(e)}")
                raise ValueError(f"Error reading PDF: {str(e)}")
        elif file_extension == '.csv':
            with open(file_path, 'r', encoding='utf-8') as file:
                csv_reader = csv.reader(file)
                return '\n'.join(','.join(row) for row in csv_reader)
        else:
            raise ValueError("Unsupported file format")

    def display_file_briefing(self, guided_prompt, keywords):
        briefing = f"Guided Prompt:\n{guided_prompt}\n\nRelevant Keywords: {keywords}"
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
                
            # Perform fuzzy matching and get keywords
            keywords = self.fuzzy_match_keywords(suggested_prompt)
            
            if messagebox.askyesno("AI Summary", "Do you want an AI-generated summary of the attached file?"):
                full_prompt = f"{user_input}\n\nAttached File Content:\n{self.attached_file_content}\n\nPossible Keywords: {keywords}"
                self.display_file_briefing(user_input, keywords)
                threading.Thread(target=self.get_model_response, args=(self.model, full_prompt)).start()
            else:
                self.display_file_briefing(user_input, keywords)
        else:
            # Normal message without attachment
            self.conversations[self.current_conversation].append({"role": "user", "content": user_input})
            self.update_chat_display()
            threading.Thread(target=self.get_model_response, args=(self.model, user_input)).start()

        self.user_input.delete(0, tk.END)
        self.attached_file_content = None  # Reset after sending

    def fuzzy_match_keywords(self, suggested_prompt):
        # Extract answers from the suggested prompt, focusing on Fields and Impacts
        fields_answers = []
        impacts_answers = []
        current_section = None

        for line in suggested_prompt.split('\n'):
            if 'Fields:' in line:
                current_section = 'Fields'
            elif 'Impacts:' in line:
                current_section = 'Impacts'
            elif ': ' in line and current_section:
                answer = line.split(': ', 1)[1]
                if current_section == 'Fields':
                    fields_answers.append(answer)
                elif current_section == 'Impacts':
                    impacts_answers.append(answer)

        # Combine Fields and Impacts answers
        combined_answers = ' '.join(fields_answers + impacts_answers)

        # Filter the keywords_df to only include rows where 'Checked' is not empty
        checked_keywords = self.keywords_df[self.keywords_df['Checked'].notna()]

        # Perform fuzzy matching
        best_match = process.extractOne(combined_answers, checked_keywords['Checked'])

        if best_match and best_match[1] > 75:  # You can adjust the threshold
            matched_row = checked_keywords[checked_keywords['Checked'] == best_match[0]].iloc[0]
            keywords = matched_row['Keywords'].split(',')
            
            # Filter out region-specific keywords
            filtered_keywords = [kw.strip() for kw in keywords if not self.is_region_specific(kw.strip())]
            
            return ', '.join(filtered_keywords)
        else:
            return ""

    def is_region_specific(self, keyword):
        region_specific_terms = ['USA', 'EU', 'China', 'Japan', 'Korea', 'Canada', 'Australia', 'UK', 'Germany', 'France', 'Italy', 'Spain']
        return any(term.lower() in keyword.lower() for term in region_specific_terms)

    def add_question(self):
        if not self.current_section:
            messagebox.showwarning("Warning", "Please select a section first.")
            return
        
        dialog = QuestionDialog(self, "Add Question")
        self.wait_window(dialog)
        
        if dialog.result:
            if 'questions' not in self.app.guided_questions[self.current_section]:
                self.app.guided_questions[self.current_section]['questions'] = []
            self.app.guided_questions[self.current_section]['questions'].append(dialog.result)
            self.populate_questions()
            self.save_questions()  # Save questions after adding a new one

    def save_questions(self):
        with open('guided_questions.json', 'w') as f:
            json.dump(self.guided_questions, f, indent=2)

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

    def get_challenger_models(self):
        return ["mixtral-8x7b-instruct-v01", "llamaguard-7b", "gemma-7b-it", "mistral-7b-instruct-v02", "phi-2", "llama-2-70b-chat", "phi-3-mini-128k-instruct", "llama-3-8b-instruct"]

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
            full_prompt = f"Context: {context}\n\n{prompt}"
            
            chunks = self.smart_chunk_prompt(full_prompt, max_tokens=4000)
            
            final_response = ""
            if len(chunks) > 1:
                responses = self.process_chunks_parallel(model, chunks, full_prompt)
                final_response = self.summarize_responses(model, "\n\n".join(responses), full_prompt)
            else:
                final_response = self.process_chunk(model, chunks[0], 1, 1, full_prompt)

            self.conversations[self.current_conversation].append({"role": "assistant", "content": final_response})
            self.master.after(0, self.update_final_response, final_response)
        except requests.exceptions.RequestException as e:
            self.master.after(0, self.show_error_popup, str(e))
        finally:
            self.is_generating = False
            self.user_input.config(state='normal')

    def process_chunks_parallel(self, model, chunks, original_prompt):
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [executor.submit(self.process_chunk, model, chunk, i+1, len(chunks), original_prompt) 
                    for i, chunk in enumerate(chunks)]
            responses = []
            for future in concurrent.futures.as_completed(futures):
                response = future.result()
                responses.append(response)
        return responses
    
    def count_tokens(self, text):
        return len(self.tokenizer.encode(text))
    
    def smart_chunk_prompt(self, prompt, max_tokens=4000):  # Reduced from 6000
        tokens = self.tokenizer.encode(prompt)
        chunks = []
        current_chunk = []
        current_length = 0
        
        sentences = re.split('(?<=[.!?]) +', prompt)
        for sentence in sentences:
            sentence_tokens = self.tokenizer.encode(sentence)
            if current_length + len(sentence_tokens) > max_tokens and current_chunk:
                chunks.append(self.tokenizer.decode(current_chunk))
                current_chunk = []
                current_length = 0
            current_chunk.extend(sentence_tokens)
            current_length += len(sentence_tokens)
        
        if current_chunk:
            chunks.append(self.tokenizer.decode(current_chunk))
        
        return chunks

    def chunk_prompt(self, prompt, max_tokens=7500):  # Reduced to leave more room for instructions
        tokens = self.tokenizer.encode(prompt)
        chunks = []
        for i in range(0, len(tokens), max_tokens):
            chunk = self.tokenizer.decode(tokens[i:i+max_tokens])
            chunks.append(chunk)
        return chunks
    
    def add_instructions_to_chunk(self, chunk, original_prompt):
        # Split the original prompt into guided prompt and user input/file content
        parts = original_prompt.split("User Input:", 1)
        
        if len(parts) > 1:
            guided_prompt = parts[0].strip()
            user_input_and_file = parts[1].strip()
        else:
            # If there's no "User Input:" separator, treat the whole thing as guided prompt
            guided_prompt = original_prompt
            user_input_and_file = ""

        # Remove "Attached File Content:" and everything after it from the guided prompt
        guided_prompt = guided_prompt.split("Attached File Content:", 1)[0].strip()

        # Construct the instructions
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

    def process_chunk(self, model, chunk, chunk_num, total_chunks, original_prompt):
        url = "https://opensource-challenger-api.prdlvgpu1.aiaccel.dell.com/v1/chat/completions"
        headers = {
            'accept': 'application/json',
            'api-key': self.api_key,
            'Content-Type': 'application/json'
        }
        
        system_message = "You are a helpful AI assistant. Respond directly to the user without mentioning yourself in the third person or commenting on the nature of the response."
        
        if chunk_num > 1:
            chunk_with_instructions = self.add_instructions_to_chunk(chunk, original_prompt)
        else:
            chunk_with_instructions = chunk
        
        # Construct messages array with proper alternation
        messages = [
            {"role": "system", "content": system_message},
        ]
        
        # Add previous messages from the conversation if available
        if self.current_conversation and self.conversations[self.current_conversation]:
            for message in self.conversations[self.current_conversation]:
                messages.append({"role": message['role'], "content": message['content']})
        
        # Add the current chunk as a user message
        messages.append({"role": "user", "content": chunk_with_instructions})
        
        # Count tokens in the input
        input_tokens = sum(self.count_tokens(message['content']) for message in messages)
        
        # Calculate available tokens for the response
        max_context_length = 8192
        available_tokens = max_context_length - input_tokens - 100  # Leave some buffer
        
        # If available tokens is negative, we need to truncate the input
        if available_tokens <= 0:
            # Truncate the chunk_with_instructions
            max_chunk_tokens = max_context_length - self.count_tokens(system_message) - 100
            chunk_tokens = self.tokenizer.encode(chunk_with_instructions)[:max_chunk_tokens]
            chunk_with_instructions = self.tokenizer.decode(chunk_tokens)
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": chunk_with_instructions}
            ]
            available_tokens = max_context_length - self.count_tokens(system_message) - self.count_tokens(chunk_with_instructions) - 100

        # Ensure max_tokens is within the available range
        max_tokens = min(int(self.max_tokens_entry.get()), available_tokens)
        max_tokens = max(max_tokens, 1)  # Ensure it's at least 1
        
        data = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature_scale.get(),
            "top_p": 0.95,
            "max_tokens": max_tokens,
            "stream": True
        }
        
        response = requests.post(url, headers=headers, json=data, stream=True, verify=False)
        chunk_response = ""
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
                                chunk_response += delta['content']
                    except json.JSONDecodeError as e:
                        print(f"JSON Decode Error: {e}")
                        print(f"Problematic line: {decoded_line}")
                        continue
                else:
                    print(f"Unexpected line format: {decoded_line}")
        
        return chunk_response

    def update_processing_info(self, info):
        self.chat_display.config(state='normal')
        self.chat_display.insert("end", f"{info}\n")
        self.chat_display.config(state='disabled')
        self.chat_display.see("end")
        
    def summarize_responses(self, model, combined_response, original_prompt):
        chunks = self.smart_chunk_prompt(combined_response, max_tokens=4000)
        
        if len(chunks) == 1:
            return self.process_summary_chunk(model, chunks[0], original_prompt)
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [executor.submit(self.process_summary_chunk, model, chunk, original_prompt) for chunk in chunks]
            summaries = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        # Combine meaningful parts from all summaries
        combined_summary = self.combine_meaningful_parts(summaries)
        
        # If the combined summary is still too long, summarize it again
        if len(self.tokenizer.encode(combined_summary)) > 4000:
            return self.summarize_responses(model, combined_summary, original_prompt)
        
        return combined_summary
    
    def combine_meaningful_parts(self, summaries):
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
    
    def process_summary_chunk(self, model, chunk, original_prompt):
        url = "https://opensource-challenger-api.prdlvgpu1.aiaccel.dell.com/v1/chat/completions"
        headers = {
            'accept': 'application/json',
            'api-key': self.api_key,
            'Content-Type': 'application/json'
        }
        
        instruction_match = re.search(r"Please provide .+?:\n", original_prompt, re.DOTALL)
        if instruction_match:
            instructions = instruction_match.group(0)
            summary_prompt = f"{instructions}\n\nPlease summarize and consolidate the following response chunk, following the format specified above:\n\n{chunk}"
        else:
            summary_prompt = f"Please summarize and consolidate the following response chunk:\n\n{chunk}"

        system_message = "You are a helpful AI assistant. Summarize the given information concisely. If a section is not applicable or information is not available, simply write 'Not applicable' for that section."
        
        # Construct messages array
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": summary_prompt}
        ]
        
        # Count tokens in the input
        input_tokens = sum(self.count_tokens(message['content']) for message in messages)
        
        # Calculate available tokens for the response
        max_context_length = 8192
        available_tokens = max_context_length - input_tokens - 100  # Leave some buffer
        
        # If available tokens is negative, we need to truncate the input
        if available_tokens <= 0:
            # Truncate the summary_prompt
            max_prompt_tokens = max_context_length - self.count_tokens(system_message) - 100
            prompt_tokens = self.tokenizer.encode(summary_prompt)[:max_prompt_tokens]
            summary_prompt = self.tokenizer.decode(prompt_tokens)
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": summary_prompt}
            ]
            available_tokens = max_context_length - self.count_tokens(system_message) - self.count_tokens(summary_prompt) - 100

        # Ensure max_tokens is within the available range
        max_tokens = min(int(self.max_tokens_entry.get()), available_tokens)
        max_tokens = max(max_tokens, 1)  # Ensure it's at least 1

        data = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature_scale.get(),
            "top_p": 0.95,
            "max_tokens": max_tokens,
            "stream": True
        }
        
        response = requests.post(url, headers=headers, json=data, stream=True, verify=False)
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
                    except json.JSONDecodeError as e:
                        print(f"JSON Decode Error: {e}")
                        print(f"Problematic line: {decoded_line}")
                        continue
                else:
                    print(f"Unexpected line format: {decoded_line}")
                        
        return summary_response    
    
    def update_response(self, response):
        self.chat_display.config(state='normal')
        last_assistant_index = self.chat_display.search("Assistant:", "end", backwards=True, stopindex="1.0")
        if last_assistant_index:
            self.chat_display.delete(last_assistant_index, "end-1c")
            self.chat_display.insert(last_assistant_index, f"Assistant: {response}\n\n")
        else:
            self.chat_display.insert("end", f"Assistant: {response}\n\n")
        self.chat_display.config(state='disabled')
        self.chat_display.see("end")

    def update_final_response(self, response):
        self.chat_display.config(state='normal')
        last_assistant_index = self.chat_display.search("Assistant:", "end", backwards=True, stopindex="1.0")
        if last_assistant_index:
            self.chat_display.delete(last_assistant_index, "end-1c")
        self.chat_display.insert("end", f"Assistant: {response}\n\n")
        self.chat_display.config(state='disabled')
        self.chat_display.see("end")

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