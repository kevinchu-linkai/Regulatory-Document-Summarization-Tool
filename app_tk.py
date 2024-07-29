import tkinter as tk
from tkinter import ttk, scrolledtext
import requests
import json
import threading

class LLMPlayground:
    def __init__(self, master):
        self.master = master
        master.title("LLM Playground")
        master.geometry("800x600")

        self.conversations = {}
        self.current_conversation = None

        self.create_widgets()

    def create_widgets(self):
        # Create sidebar
        sidebar = ttk.Frame(self.master, width=200, relief='sunken', borderwidth=1)
        sidebar.pack(side='left', fill='y', expand=False)

        # Create main chat area
        chat_area = ttk.Frame(self.master)
        chat_area.pack(side='right', fill='both', expand=True)

        # Sidebar widgets
        ttk.Button(sidebar, text="New Chat", command=self.new_chat).pack(pady=10)
        ttk.Label(sidebar, text="Your conversations").pack(pady=5)
        self.conversation_listbox = tk.Listbox(sidebar, width=25)
        self.conversation_listbox.pack(pady=5, padx=5, fill='x')
        self.conversation_listbox.bind('<<ListboxSelect>>', self.on_conversation_select)

        ttk.Label(sidebar, text="Select Ollama Model").pack(pady=5)
        self.model_combobox = ttk.Combobox(sidebar, values=self.get_ollama_models())
        self.model_combobox.pack(pady=5, padx=5)
        self.model_combobox.set("Select a model")

        # Chat area widgets
        self.chat_display = scrolledtext.ScrolledText(chat_area, state='disabled')
        self.chat_display.pack(pady=10, padx=10, fill='both', expand=True)

        self.user_input = ttk.Entry(chat_area)
        self.user_input.pack(pady=10, padx=10, fill='x')

        ttk.Button(chat_area, text="Send", command=self.send_message).pack()

    def get_ollama_models(self):
        try:
            response = requests.get("http://localhost:11434/api/tags")
            models = response.json().get("models", [])
            return [model["name"].split(':')[0] for model in models]
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
            self.chat_display.insert(tk.END, f"{message['role'].capitalize()}: {message['content']}\n\n")
        self.chat_display.config(state='disabled')
        self.chat_display.see(tk.END)

    def send_message(self):
        user_input = self.user_input.get()
        if not user_input or not self.current_conversation:
            return

        self.conversations[self.current_conversation].append({"role": "user", "content": user_input})
        self.update_chat_display()
        self.user_input.delete(0, tk.END)

        model = self.model_combobox.get()
        if model != "Select a model":
            threading.Thread(target=self.get_model_response, args=(model, user_input)).start()

    def get_model_response(self, model, prompt):
        try:
            url = "http://localhost:11434/api/generate"
            data = {
                "model": model,
                "prompt": prompt
            }
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
            print(f"Error: {e}")
            self.master.after(0, self.show_error, str(e))

    def update_response(self, response_so_far):
        self.chat_display.config(state='normal')
        self.chat_display.delete('1.0', tk.END)
        for message in self.conversations[self.current_conversation]:
            self.chat_display.insert(tk.END, f"{message['role'].capitalize()}: {message['content']}\n\n")
        self.chat_display.insert(tk.END, f"Assistant: {response_so_far}")
        self.chat_display.config(state='disabled')
        self.chat_display.see(tk.END)

    def show_error(self, error_message):
        self.chat_display.config(state='normal')
        self.chat_display.insert(tk.END, f"Error: {error_message}\n\n")
        self.chat_display.config(state='disabled')
        self.chat_display.see(tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    app = LLMPlayground(root)
    root.mainloop()