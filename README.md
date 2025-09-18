A mathematician's copilot -- find theorems faster!

`streamlit run test_app.py` to run the streamlit app


The arXiv API uses a specific format for its queries, which allows you to be very precise. The most common prefixes are:
ti: - Search for words in the Title.
au: - Search for an Author's name.
abs: - Search for words in the Abstract (the summary).
cat: - Search for papers in a specific Category (e.g., math.AP, cs.AI).
You can combine these with boolean operators:
AND: Returns papers that match both terms.
OR: Returns papers that match either term.
ANDNOT: Excludes papers that match the term.

`python arxiv_analyzer_scaled.py --query "cat:math.GM" --max_results 3` Example to run