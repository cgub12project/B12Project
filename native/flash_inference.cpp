#include <android/log.h>
#include <jni.h>
#include <llama.h>

#include <algorithm>
#include <mutex>
#include <string>
#include <unistd.h>
#include <vector>

namespace {

constexpr char LOG_TAG[] = "FlashLocalModel";
constexpr int CONTEXT_SIZE = 2048;
constexpr int BATCH_SIZE = 512;

std::mutex inference_mutex;
llama_model *loaded_model = nullptr;
std::string loaded_path;
bool backend_initialized = false;

void log_error(const char *message) {
    __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, "%s", message);
}

std::string to_string(JNIEnv *env, jstring value) {
    const char *chars = env->GetStringUTFChars(value, nullptr);
    if (chars == nullptr) return {};
    std::string result(chars);
    env->ReleaseStringUTFChars(value, chars);
    return result;
}

bool ensure_model(const std::string &model_path) {
    if (!backend_initialized) {
        llama_backend_init();
        backend_initialized = true;
    }
    if (loaded_model != nullptr && loaded_path == model_path) return true;

    if (loaded_model != nullptr) {
        llama_model_free(loaded_model);
        loaded_model = nullptr;
        loaded_path.clear();
    }

    const llama_model_params params = llama_model_default_params();
    loaded_model = llama_model_load_from_file(model_path.c_str(), params);
    if (loaded_model == nullptr) {
        log_error("Unable to load local GGUF model");
        return false;
    }
    loaded_path = model_path;
    return true;
}

std::vector<llama_token> tokenize(const llama_vocab *vocab, const std::string &prompt) {
    const int32_t required = llama_tokenize(
        vocab, prompt.c_str(), static_cast<int32_t>(prompt.size()), nullptr, 0, false, true);
    if (required >= 0) return {};

    std::vector<llama_token> tokens(static_cast<size_t>(-required));
    const int32_t count = llama_tokenize(
        vocab, prompt.c_str(), static_cast<int32_t>(prompt.size()), tokens.data(),
        static_cast<int32_t>(tokens.size()), false, true);
    if (count < 0) return {};
    tokens.resize(static_cast<size_t>(count));
    return tokens;
}

bool decode_tokens(llama_context *context, llama_batch &batch, const std::vector<llama_token> &tokens) {
    for (size_t offset = 0; offset < tokens.size(); offset += BATCH_SIZE) {
        const int32_t count = static_cast<int32_t>(std::min(tokens.size() - offset, static_cast<size_t>(BATCH_SIZE)));
        batch.n_tokens = count;
        for (int32_t i = 0; i < count; ++i) {
            batch.token[i] = tokens[offset + static_cast<size_t>(i)];
            batch.pos[i] = static_cast<llama_pos>(offset + static_cast<size_t>(i));
            batch.n_seq_id[i] = 1;
            batch.seq_id[i][0] = 0;
            batch.logits[i] = offset + static_cast<size_t>(i) + 1 == tokens.size();
        }
        if (llama_decode(context, batch) != 0) return false;
    }
    return true;
}

std::string token_piece(const llama_vocab *vocab, llama_token token) {
    std::vector<char> buffer(32);
    int32_t count = llama_token_to_piece(vocab, token, buffer.data(), static_cast<int32_t>(buffer.size()), 0, true);
    if (count < 0) {
        buffer.resize(static_cast<size_t>(-count));
        count = llama_token_to_piece(vocab, token, buffer.data(), static_cast<int32_t>(buffer.size()), 0, true);
    }
    return count > 0 ? std::string(buffer.data(), static_cast<size_t>(count)) : std::string();
}

} // namespace

extern "C" JNIEXPORT jstring JNICALL
Java_com_frauddetector_service_LocalModelNative_classify(
    JNIEnv *env,
    jobject,
    jstring jmodel_path,
    jstring jprompt,
    jint max_tokens
) {
    std::lock_guard<std::mutex> lock(inference_mutex);
    const std::string model_path = to_string(env, jmodel_path);
    const std::string prompt = to_string(env, jprompt);
    if (model_path.empty() || prompt.empty() || !ensure_model(model_path)) return nullptr;

    const llama_vocab *vocab = llama_model_get_vocab(loaded_model);
    const std::vector<llama_token> prompt_tokens = tokenize(vocab, prompt);
    if (prompt_tokens.empty() || prompt_tokens.size() >= CONTEXT_SIZE - 1) {
        log_error("Prompt cannot fit in local model context");
        return nullptr;
    }

    llama_context_params context_params = llama_context_default_params();
    context_params.n_ctx = CONTEXT_SIZE;
    context_params.n_batch = BATCH_SIZE;
    context_params.n_ubatch = BATCH_SIZE;
    const int cpu_count = static_cast<int>(sysconf(_SC_NPROCESSORS_ONLN));
    const int threads = std::max(2, std::min(4, cpu_count - 2));
    context_params.n_threads = threads;
    context_params.n_threads_batch = threads;

    llama_context *context = llama_init_from_model(loaded_model, context_params);
    if (context == nullptr) {
        log_error("Unable to create local model context");
        return nullptr;
    }

    llama_batch batch = llama_batch_init(BATCH_SIZE, 0, 1);
    std::string output;
    if (!decode_tokens(context, batch, prompt_tokens)) {
        llama_batch_free(batch);
        llama_free(context);
        log_error("Failed to decode local model prompt");
        return nullptr;
    }

    llama_sampler *sampler = llama_sampler_init_greedy();
    int32_t position = static_cast<int32_t>(prompt_tokens.size());
    const int32_t limit = std::min(std::max(max_tokens, 1), CONTEXT_SIZE - position - 1);
    for (int32_t generated = 0; generated < limit; ++generated) {
        const llama_token token = llama_sampler_sample(sampler, context, -1);
        if (llama_vocab_is_eog(vocab, token)) break;
        output += token_piece(vocab, token);

        batch.n_tokens = 1;
        batch.token[0] = token;
        batch.pos[0] = position++;
        batch.n_seq_id[0] = 1;
        batch.seq_id[0][0] = 0;
        batch.logits[0] = true;
        if (llama_decode(context, batch) != 0) break;
    }

    llama_sampler_free(sampler);
    llama_batch_free(batch);
    llama_free(context);
    return env->NewStringUTF(output.c_str());
}
