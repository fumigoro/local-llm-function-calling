"""A generator for the responses to a function call"""
from __future__ import annotations
from typing import Generic, TYPE_CHECKING, TypeVar

from .constrainer import Constrainer, JsonSchemaConstraint
from .model.huggingface import HuggingfaceModel

if TYPE_CHECKING:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from .model import Model
    from .prompter import FunctionCall, FunctionType, TextPrompter

PromptType = TypeVar("PromptType")
PrefixType = TypeVar("PrefixType")


class Generator(Generic[PrefixType, PromptType]):
    """Generate the function call based on the schema"""

    def __init__(
        self,
        functions: list[FunctionType],
        model: Model[PrefixType],
        prompter: TextPrompter[PrefixType, PromptType] | None = None,
    ) -> None:
        """Create a generator for the responses to a function call

        Args:
            functions (list[FunctionType]): The functions to use.
            model (Model): The model to use.
            prompter (TextPrompter): The prompter to use.
                Will use the model's default prompter if not provided.
        """
        self.model = model
        self.constrainer = Constrainer(
            self.model,
        )
        self.prompter: TextPrompter[PrefixType, PromptType] = (
            prompter or self.model.default_prompter()
        )
        self.functions = functions or []

    @classmethod
    def hf(
        cls: type[Generator[str, str]],
        functions: list[FunctionType],
        model: AutoModelForCausalLM | str,
        tokenizer: AutoTokenizer | str,
        prompter: TextPrompter[str, str] | None = None,
    ) -> Generator[str, str]:
        """Create a generator for the responses to a function call,
        using a Huggingface model

        Args:
            functions (list[FunctionType]): The functions to use.
            model (AutoTokenizer | str): The model to use.
            tokenizer (AutoTokenizer | str | None): The tokenizer to use.
                Defaults to the model's tokenizer if not provided.
            prompter (TextPrompter): The prompter to use.
                Will use the model's default prompter if not provided.

        Returns:
            The generator, using a Huggingface model
        """
        hf_model: Model[str] = HuggingfaceModel(model, tokenizer)
        return cls(functions, hf_model, prompter)

    def _begins_enum(self, prefix: str, allowed: list[str]) -> bool:
        """Check if the prefix begins one of the allowed values,
        for choosing the function to call

        Args:
            prefix (str): The prefix to check
            allowed (list[str]): The allowed values

        Returns:
            bool: Whether the prefix begins one of the allowed values
        """
        return any(
            item.startswith(prefix) or prefix.startswith(item) for item in allowed
        )

    def _generate_allowed_in_enum(self, prefix: PrefixType, allowed: list[str]) -> str:
        """Generate one of the values in an enum, for choosing the function

        Args:
            prefix (PrefixType): The prefix to use
            allowed (list[str]): The allowed values

        Returns:
            str: The generated value
        """
        if len(allowed) == 1:
            return allowed[0]
        generated = self.constrainer.generate(
            prefix,
            lambda generated: (
                self._begins_enum(generated, allowed),
                any(item.startswith(generated) for item in allowed),
            ),
        )
        for item in allowed:
            if item.startswith(generated):
                return item
        return generated

    def _choose_function(self, prompt: PromptType) -> str:
        """Choose a function to call using the LLM

        Args:
            prompt (PromptType): The prompt to use

        Returns:
            str: The function to call
        """
        prefix = self.prompter.prompt(prompt, self.functions)
        return self._generate_allowed_in_enum(
            prefix, [function["name"] for function in self.functions]
        )

    def choose_function(
        self, prompt: PromptType, function_call: str | None = None
    ) -> str:
        """Choose a function to call

        Args:
            prompt (PromptType): The prompt to use
            function_call (str | None): The function to call
                Will be generated if not provided.

        Returns:
            str: The function to call
        """
        if function_call is None:
            return self._choose_function(prompt)
        return function_call

    def generate_arguments(
        self,
        prompt: PromptType,
        function_call: str,
        max_length: int | None = None,
        max_new_tokens: int | None = None,
    ) -> str:
        """Generate the arguments for the function

        Args:
            prompt (PromptType): The prompt to use
            function_call (str): The function to call
            max_length (int | None): The maximum length of the generated sequence
            max_new_tokens (int | None): The maximum number of tokens to generate

        Returns:
            str: The arguments for the function, as a JSON string
                (may not be complete)
        """
        prefix = self.prompter.prompt(prompt, self.functions, function_call)
        constraint = JsonSchemaConstraint(
            [
                function
                for function in self.functions
                if function["name"] == function_call
            ][0][
                "parameters"
            ]  # type: ignore
        )
        generated = self.constrainer.generate(
            prefix,
            constraint,
            max_length,
            max_new_tokens,
        )
        validated = constraint.validate(generated)
        return generated[: validated.end_index] if validated.end_index else generated

    def generate(
        self,
        prompt: PromptType,
        function_call: str | None = None,
        max_length: int | None = None,
        max_new_tokens: int | None = None,
    ) -> FunctionCall:
        """Generate the function call

        Args:
            prompt (str): The prompt to use
            function_call (str | None): The function call to use.
                Will be generated if not provided.
            max_length (int | None): The maximum length of the generated sequence
            max_new_tokens (int | None): The maximum number of tokens to generate

        Returns:
            FunctionCall: The generated function call
        """
        function_name = self.choose_function(prompt, function_call)
        arguments = self.generate_arguments(
            prompt, function_name, max_new_tokens, max_length
        )
        return {"name": function_name, "parameters": arguments}
