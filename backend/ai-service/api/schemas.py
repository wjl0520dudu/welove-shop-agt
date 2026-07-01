from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FlexibleModel(BaseModel):
    """Base model that keeps backward-compatible extra fields visible."""

    class Config:
        extra = "allow"


class ParseRequest(BaseModel):
    file_path: str = Field(..., description="Document path or URL to parse")
    doc_id: int = Field(..., description="Knowledge document ID")


class SummaryRequest(BaseModel):
    question: str = Field(..., description="Conversation question used to generate a title")


class ChatRequest(BaseModel):
    question: str = Field(..., description="User input text")
    context: str = Field("", description="Conversation context passed by Java")
    conversation_id: Optional[str] = Field(None, description="Conversation ID for memory and cart context")
    username: Optional[str] = Field(None, description="Current user's display name")
    user_id: Optional[str] = Field(None, description="Current user ID for cart operations")
    is_admin: bool = Field(False, description="Whether the caller is an admin")
    gender: Optional[str] = Field(None, description="User gender profile")
    skin_type: Optional[str] = Field(None, description="User skin type profile")
    preference_tags: Optional[List[str]] = Field(None, description="User preference tags")
    jwt_token: Optional[str] = Field(None, description="JWT token forwarded by Java for Java API callbacks")


class AgentRunRequest(BaseModel):
    input: str = Field(..., description="Agent input text")
    conversation_id: Optional[str] = Field(None, description="Conversation ID")
    user_id: Optional[str] = Field(None, description="User ID")
    context: Optional[str] = Field("", description="Conversation context")
    goal: Optional[str] = Field(None, description="Agent run goal")
    run_id: Optional[str] = Field(None, description="Client supplied run ID")
    trace_id: Optional[str] = Field(None, description="Client supplied trace ID")
    stream: bool = Field(False, description="Whether the caller expects stream mode")
    is_admin: bool = Field(False, description="Whether the caller is an admin")


class ImageRecognizeRequest(BaseModel):
    image_url: Optional[str] = Field(None, description="Image URL for future JSON recognition mode")
    image_base64: Optional[str] = Field(None, description="Base64 image payload for future JSON recognition mode")


class VoiceRecognizeRequest(BaseModel):
    audio_url: Optional[str] = Field(None, description="Audio URL for future JSON recognition mode")
    audio_base64: Optional[str] = Field(None, description="Base64 audio payload for future JSON recognition mode")
    audio_format: str = Field("m4a", description="Audio format")


class Source(FlexibleModel):
    doc_id: Optional[Any] = Field(None, description="Source document ID")
    doc: Optional[str] = Field(None, description="Source document path or title")
    doc_name: Optional[str] = Field(None, description="Source document display name")
    source: Optional[str] = Field(None, description="Source text or identifier")
    page: Optional[int] = Field(None, description="Page number")
    chunk_index: Optional[int] = Field(None, description="Chunk index")
    score: Optional[float] = Field(None, description="Retrieval score")


class ProductCard(FlexibleModel):
    product_id: Optional[Any] = Field(None, description="Product ID")
    title: str = Field("", description="Product title")
    brand: str = Field("", description="Product brand")
    price: Optional[float] = Field(None, description="Display price")
    base_price: Optional[float] = Field(None, description="Base price")
    image_url: str = Field("", description="Product image URL")
    rating: Optional[float] = Field(None, description="Product rating")
    sales_count: Optional[int] = Field(None, description="Sales count")
    sub_category: str = Field("", description="Product sub-category")
    reason: str = Field("", description="Recommendation reason")


class ConfirmButton(FlexibleModel):
    type: str = Field(..., description="Button action type")
    label: str = Field(..., description="Button label")


class ConfirmCard(FlexibleModel):
    type: str = Field("confirm_card", description="Card type")
    message: str = Field("", description="Confirmation message")
    action: Optional[str] = Field(None, description="Pending action")
    product: Optional[Dict[str, Any]] = Field(None, description="Single product payload")
    products: Optional[List[Dict[str, Any]]] = Field(None, description="Batch product payload")
    buttons: List[ConfirmButton] = Field(default_factory=list, description="Confirmation buttons")


class CartItem(FlexibleModel):
    product_id: Optional[Any] = Field(None, description="Product ID")
    title: str = Field("", description="Product title")
    brand: str = Field("", description="Product brand")
    base_price: Optional[float] = Field(None, description="Base price")
    image_url: str = Field("", description="Product image URL")
    rating: Optional[float] = Field(None, description="Product rating")
    quantity: Optional[int] = Field(None, description="Cart quantity")


class CartSelection(FlexibleModel):
    type: str = Field("cart_selection", description="Card type")
    message: str = Field("", description="Selection message")
    items: List[CartItem] = Field(default_factory=list, description="Selectable cart items")


class CartList(FlexibleModel):
    type: str = Field("cart_list", description="Card type")
    message: str = Field("", description="Cart list message")
    items: List[CartItem] = Field(default_factory=list, description="Cart items")


class AgentStepDTO(FlexibleModel):
    step_id: Optional[str] = Field(None, description="Step ID")
    step_type: Optional[str] = Field(None, description="Step type")
    step_name: str = Field("", description="Step name")
    status: str = Field("", description="Step status")
    input_data: Optional[Any] = Field(None, description="Step input")
    output_data: Optional[Any] = Field(None, description="Step output")
    error_message: Optional[str] = Field(None, description="Step error message")
    duration_ms: Optional[float] = Field(None, description="Step duration in milliseconds")
    tool_call_id: Optional[str] = Field(None, description="Related tool call ID")
    start_time: Optional[float] = Field(None, description="Step start timestamp")
    end_time: Optional[float] = Field(None, description="Step end timestamp")


class ToolCallDTO(FlexibleModel):
    tool_call_id: Optional[str] = Field(None, description="Tool call ID")
    tool_name: str = Field("", description="Tool name")
    input_params: Dict[str, Any] = Field(default_factory=dict, description="Tool input parameters")
    output: Dict[str, Any] = Field(default_factory=dict, description="Tool output")
    status: str = Field("", description="Tool call status")
    duration_ms: Optional[float] = Field(None, description="Tool call duration in milliseconds")
    error_message: Optional[str] = Field(None, description="Tool call error message")
    timestamp: Optional[float] = Field(None, description="Tool call timestamp")


class IntermediateConclusionDTO(FlexibleModel):
    step_id: Optional[str] = Field(None, description="Related step ID")
    conclusion_type: str = Field("", description="Conclusion type")
    content: Any = Field(None, description="Conclusion content")
    confidence: float = Field(0.0, description="Conclusion confidence")
    sources: List[Source] = Field(default_factory=list, description="Conclusion sources")


class AIResponse(FlexibleModel):
    answer: str = Field("", description="Final AI answer")
    sources: List[Source] = Field(default_factory=list, description="RAG sources")
    task_type: str = Field("unknown", description="Task type")
    product_cards: List[ProductCard] = Field(default_factory=list, description="Product cards")
    confirm_card: Optional[ConfirmCard] = Field(None, description="Cart confirmation card")
    cart_selection: Optional[CartSelection] = Field(None, description="Cart selection card")
    cart_list: Optional[CartList] = Field(None, description="Cart list card")
    run_id: Optional[str] = Field(None, description="Agent run ID")
    trace_id: Optional[str] = Field(None, description="Trace ID")
    status: str = Field("completed", description="Run status")
    error: bool = Field(False, description="Whether this response is an error")
    error_code: Optional[str] = Field(None, description="Stable error code")
    message: Optional[str] = Field(None, description="Stable error or status message")
    has_sources: bool = Field(False, description="Whether sources are present")
    steps: List[AgentStepDTO] = Field(default_factory=list, description="Agent steps")
    tool_calls: List[ToolCallDTO] = Field(default_factory=list, description="Tool calls")
    intermediate_conclusions: List[IntermediateConclusionDTO] = Field(
        default_factory=list,
        description="Intermediate conclusions",
    )


class StreamEvent(FlexibleModel):
    type: str = Field(..., description="SSE event type")
    run_id: Optional[str] = Field(None, description="Agent run ID")
    trace_id: Optional[str] = Field(None, description="Trace ID")
    task_type: Optional[str] = Field(None, description="Task type")
    content: Optional[str] = Field(None, description="Token or message content")
    response: Optional[AIResponse] = Field(None, description="Full response on end events")
    error: bool = Field(False, description="Whether this event is an error")
    error_code: Optional[str] = Field(None, description="Stable error code")
    message: Optional[str] = Field(None, description="Stable error or status message")


class ErrorResponse(AIResponse):
    error: bool = True
    status: str = "failed"


class ImageRecognizeResponse(BaseModel):
    text: str = Field("", description="Recognized image text")
    error: bool = Field(False, description="Whether recognition failed")
    error_code: Optional[str] = Field(None, description="Stable error code")
    message: Optional[str] = Field(None, description="Error message")


class VoiceRecognizeResponse(BaseModel):
    text: str = Field("", description="Recognized voice text")
    error: bool = Field(False, description="Whether recognition failed")
    error_code: Optional[str] = Field(None, description="Stable error code")
    message: Optional[str] = Field(None, description="Error message")

