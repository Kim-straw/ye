package com.example.simplekanyewest.Dto;


import com.example.simplekanyewest.Entity.Memo;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class MemoResponseDto {
    private Long memoId;
    private String title;
    private String content;

    public MemoResponseDto(Memo memo) {
        this.memoId = memo.getMemoId();
        this.title = memo.getTitle();
        this.content = memo.getContent();
    }
}