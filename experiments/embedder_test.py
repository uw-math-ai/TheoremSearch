from sentence_transformers import SentenceTransformer

model = SentenceTransformer("math-similarity/Bert-MLM_arXiv-MP-class_zbMath")

embedding1 = model.encode("Complex numbers")
embedding2 = model.encode("\\R")

similarities = model.similarity(embedding1, embedding2)
print(similarities)