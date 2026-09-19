# INCOSE Requirements Assistant

This prototype reads a list of engineering requirements and checks each one against seven INCOSE quality criteria (Necessity, Appropriateness, Unambiguity, Completeness, Singularity, Correctness, and Conformance). It uses the user's choice of Claude, ChatGPT, or Ollama for analysis. A reviewer can then accept or fix each problem it finds and download a corrected Word document.

## How to install and run 

1. Clone the repository on your local machine. You can do this by running the following command in your terminal:
```
git clone https://github.com/jshefa/requirements-assistant-app.git
``` 
2. First ensure that Docker is installed and running. You can install it at the [official Docker website](https://docs.docker.com/desktop/setup/install/windows-install/). The Docker engine NEEDS to be running before the next step. 
3. From the project's root directory, run 
```
docker compose up --build
```
To run with local model support, run with the ollama profiles as shown below. The `ollama` profile runs on the CPU, while the `ollama-nvidia` profile runs on the GPU for nvidia graphics cards. The latter is recommended if the hardware is available as CPU analysis is significantly slower than GPU. Running with local model support for the first time will take a few minutes, as the LLM model has to be installed.

```
# for CPU analysis 
docker compose --profile ollama up --build

# for Nvidia GPU analysis (recommended)
docker compose --profile ollama-nvidia up --build
```
4. Navigate to localhost:3001 on your preferred browser to use the prototype. 

## Using the prototype

1. First, run the prototype using the instructions above.
2. Next, set your desired API key through the "Change API Keys" modal window. If you are running with Ollama, then this is unecessary. If you do not already have an API key, you can get them from the [Anthropic Dashboard](https://platform.claude.com/dashboard) or [OpenAI Dashboard](https://platform.openai.com/home).
3. Choose the provider that you would like to run analysis on. 
4. Choose your requirement file. The prototype supports both `.txt` and `.oml`, however ensure it fits the following format. 

For `.txt` files, each requirement should begin with a unique requirement ID followed by the requirement text:

```text
FR1: The system shall move the payload from the origin to the destination.
FR2: The system shall return the payload from the destination to the origin.
PR1: The system shall position the payload within +/- 2.5 mm in each Cartesian direction. 
```

For .oml files, each requirement should be represented as a req:Requirement instance containing a name, ID, and natural-language description as followed:

```
instance item-33334 : req:Requirement [
    tlo:hasName "Displace"
    tlo:hasID "33334"
    tlo:hasNaturalLanguageDescription "The System shall move a point mass from an origin point to a fixed destination point."
]

instance item-33335 : req:Requirement [
    tlo:hasName "Return"
    tlo:hasID "33335"
    tlo:hasNaturalLanguageDescription "The System shall move the point mass from the destination point back to the origin point."
]
```

5. Choose your context files if desired; this is optional. You can upload a separate .txt system context document, a .txt ConOps document, and a related ConOps image. 
6. Click analyze when you are ready. The analysis time will depend on your number of requirements and provider. For a small requirements file of 10 requirements you can expect a runtime of under a minute, however a file with hundreds of requirements can take over 10 minutes. 