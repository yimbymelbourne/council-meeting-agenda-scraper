# This file should include all the functions that are needed to run the LLM
import ollama


def llm_reader(agenda: str) -> str:
    prompt = f"""
  You are an urbanist who wants to keep up to date with planning items and applications in your local council.
  Can you write a list with four dot points that includes a quick summary of any items on this agenda relating to: 
  1) New changes to heritage overlays
  2) New changes to heritage policy
  3) New information about design & development overlays
  4) New information about neighbourhood character overlays
  5) New information about or changes to homelessness policy

  Then can you write a summary of each new planning application for a mixed-use or residential development that is mentioned in the document.
  Where possible, this summary should include: 
  - page or section numbers where the application starts
  - location and address of the development
  - total number of dwellings proposed
  - total number of storeys proposed
  - the number of objections and support letters received by the council
  - the council's recommendation for the application
  - any other notable features of the development

  The document begins below: 

  {agenda}
  """

    response = ollama.chat(
        model="mistral",
        messages=[
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )
    output = response["message"]["content"]
    print(output)
    return output


with open("Maribyrnong_latest.txt", "r") as f:
    agenda = f.read()


prompt = f"""
You are an urbanist who wants to keep up to date with planning items and applications in your local council.
Can you write a list with four dot points that includes a quick summary of any items on this agenda relating to: 
1) New changes to heritage overlays
2) New changes to heritage policy
3) New information about design & development overlays
4) New information about neighbourhood character overlays
5) New information about or changes to homelessness policy

Then can you write a summary of each new planning application for a mixed-use or residential development that is mentioned in the document.
Where possible, this summary should include: 
- page or section numbers where the application starts
- location and address of the development
- total number of dwellings proposed
- total number of storeys proposed
- the number of objections and support letters received by the council
- the council's recommendation for the application
- any other notable features of the development

The document begins below: 

{agenda}
"""

print(prompt)

# response = ollama.generate(model='yarn-llama2:7b-128k', prompt=prompt)
response = ollama.generate(model="yarn-llama2", prompt=prompt)


output = response["message"]["content"]
print(output)


from pypdf import PdfReader
import requests

# Open the PDF file
pdf_file = open("files/maribyrnong_agenda.pdf", "rb")

# Create a PDF reader object
pdf_reader = PdfReader(pdf_file)

# Initialize an empty string to store the text
pdf_text = ""

# Read each page of the PDF and append its text to pdf_text
for page in pdf_reader.pages:
    pdf_text += page.extract_text()

# Close the PDF file
pdf_file.close()

# Define the guiding prompt
guiding_prompt = "Please summarize the following text:"

# Send the text to the Ollama LLM
response = requests.post(
    "http://localhost:11434/api/generate",
    json={"model": "mistral", "prompt": f"{guiding_prompt}\n{pdf_text}"},
)

# Print the summarized text
print(response.text)
