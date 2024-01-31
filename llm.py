from datetime import datetime
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_openai import OpenAIEmbeddings
from langchain.vectorstores.chroma import Chroma

from openai import OpenAI

from _dataclasses import Council

import os.path
from dotenv import dotenv_values

config = dotenv_values(".env") if os.path.exists(".env") else {}

POLICY_CHANGES = [
    "Heritage policy",
    "Homelessness policy",
    "Housing policy",
    "Heritage overlays",
    "Design and development overlays",
    "Neighbourhood character overlays",
]

CHAT_MODEL = (
    "gpt-4"  # "gpt-4-turbo-preview"  # "gpt-3.5-turbo-1106" BEST: "gpt-4-turbo-preview"
)

EMBEDDINGS_MODEL = "text-embedding-3-small"  # BEST: "text-embedding-3-small"
EMBEDDINGS_RETRIEVAL_COUNT = 7  # BEST: 10

DEFAULT_MESSAGE = {
    "role": "system",
    "content": "You are a passionate urbanist who does important summarisation work to make your city better. You are smart, succinct, and direct, and you use markdown formatting and dot points where possible.",
}


def load_pdf(agenda_name: str):
    pages = PyMuPDFLoader(f"files/{agenda_name}").load()
    return pages


def embed_pdf(pdf, council) -> Chroma:
    # Create an embedding function
    embeddings = OpenAIEmbeddings(
        model=EMBEDDINGS_MODEL,
        openai_api_key=config["OPENAI_API_KEY"],
        dimensions=768,
    )

    # Create a vector database
    vectordb = Chroma.from_documents(pdf, embeddings, collection_name=council)
    return vectordb


def policy_checker(db: Chroma, llm: OpenAI, policy: str):
    # Query the vector database
    query = f"Are there any changes to {policy} policy in this document?"
    results = db.similarity_search(query, k=EMBEDDINGS_RETRIEVAL_COUNT)
    print(f"Found {len(results)} results")

    context = ""
    for result in results:
        context += result.page_content + "\n\n"

    prompt = f"""
    Q: What changes if any are there to the Council's {policy} policy in this meeting?
    If there are no changes to the policy then answer simply "No changes."
    Consider the following context:
    
    {context}
    """

    response = llm.chat.completions.create(
        model=CHAT_MODEL,
        messages=[DEFAULT_MESSAGE, {"role": "user", "content": prompt}],
        max_tokens=300,
    )

    response = response.choices[0].message.content
    return response


def development_getter(db: Chroma, llm: OpenAI) -> list[str]:
    query = f"Table of contents, repeated addresses, planning permit application, council reports, officer reports"
    results = db.similarity_search(query, k=EMBEDDINGS_RETRIEVAL_COUNT)
    print(f"Found {len(results)} results")

    context = ""
    for result in results:
        context += result.page_content + "\n\n"

    prompt = f"""
    Q: From the following context, can you please list the planning permit applications in this document?
    Please return only a list containing each development on a new line in this format:
    - Address, permit number, page number
    
    If there are no planning permit applications in this document, please return "No planning permit applications in this document."
    
    Context begins:
        
    {context}
    """

    response = llm.chat.completions.create(
        model=CHAT_MODEL,
        messages=[DEFAULT_MESSAGE, {"role": "user", "content": prompt}],
        max_tokens=200,
    )

    response = response.choices[0].message.content

    if response == "No planning permit applications in this document.":
        return []

    development_list = response.split("\n")
    development_list = [
        development for development in development_list if development != ""
    ]
    development_list = [development.lstrip(" - ") for development in development_list]

    return development_list


def development_summariser(db: Chroma, llm: OpenAI, development: str) -> str:
    query = f"Summarise the development application: {development}"
    results = db.similarity_search(query, k=EMBEDDINGS_RETRIEVAL_COUNT)
    print(f"Found {len(results)} results")

    context = ""
    for result in results:
        context += result.page_content + "\n\n"

    prompt = f"""
    Q: Write a summary of the planning application for {development}.
    Where possible, this summary should include: 
    - page or section numbers where the application starts
    - location and address of the development
    - total number of dwellings proposed
    - total number of storeys proposed
    - the number of objections and support letters received by the council
    - the council's recommendation for the application
    - any other notable features of the development
        
    Context begins:
        
    {context}
    """

    response = llm.chat.completions.create(
        model=CHAT_MODEL,
        messages=[DEFAULT_MESSAGE, {"role": "user", "content": prompt}],
        max_tokens=500,
    )

    response = response.choices[0].message.content

    return response


def llm_responses(db):
    llm = OpenAI(api_key=config["OPENAI_API_KEY"])

    responses = {}

    for policy in POLICY_CHANGES:
        response = policy_checker(db, llm, policy)
        print(response)
        responses[policy] = response

    development_list = development_getter(db, llm)
    print(development_list)
    if len(development_list) > 0:
        for development in development_list:
            response = development_summariser(db, llm, development)
            print(response)
            responses[development] = response
    else:
        responses["No developments"] = "No developments identified in this agenda."

    return responses


def llm(agenda_name: str):
    print("Loading PDF...")
    pdf = load_pdf(agenda_name)
    # pickle.dump(pdf, open(f"{agenda_name}.pkl", "wb"))
    print("PDF loaded!")

    # pdf = pickle.load(open(f"{agenda_name}.pkl", "rb"))

    print("Embedding PDF...")
    db = embed_pdf(pdf)
    print("PDF embedded!")

    print("Sending PDF to LLM...")
    responses = llm_responses(db)
    print("Done!")

    with open(
        f"logs/{agenda_name}_{CHAT_MODEL}_embeddings-{EMBEDDINGS_RETRIEVAL_COUNT}_{datetime.now()}.md",
        "w",
    ) as f:
        for response in responses:
            print(f"# {response}\n{responses[response]}\n\n")
            f.write(f"# {response}\n{responses[response]}\n\n")
    return


def llm_processor(council: Council):
    print("Loading PDF...")
    pdf = PyMuPDFLoader(f"files/{council.name}_latest.pdf").load()
    print("PDF loaded!")

    print("Embedding PDF...")
    db = embed_pdf(pdf, council.name)
    print("PDF embedded!")

    print("Sending PDF to LLM...")
    responses = llm_responses(db)
    print("Done!")

    result = ""
    with open(
        f"logs/{council.name}_{CHAT_MODEL}_embeddings-{EMBEDDINGS_RETRIEVAL_COUNT}_{datetime.now()}.md",
        "w",
    ) as f:
        for response in responses:
            string = f"# {response}\n{responses[response]}\n\n"
            print(string)
            f.write(string)
            result += string

    return result


if __name__ == "__main__":
    agenda_name = "merribek-240927.pdf"
    llm(agenda_name)
