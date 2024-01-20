# This file should include all the functions that are needed to run the LLM

prompt = f'''
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
'''