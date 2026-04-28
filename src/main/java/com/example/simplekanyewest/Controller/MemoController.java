package com.example.simplekanyewest.Controller;


import com.example.simplekanyewest.CommonResponse;
import com.example.simplekanyewest.Dto.MemoRequestDto;
import com.example.simplekanyewest.Dto.MemoResponseDto;
import com.example.simplekanyewest.Entity.Memo;
import com.example.simplekanyewest.Service.MemoService;
import lombok.AllArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@AllArgsConstructor
@RequestMapping("/api/memo") //모든 메모 API의 기본 URL
public class MemoController {
    public  final MemoService memoService;

    @PostMapping
    public ResponseEntity<CommonResponse<MemoResponseDto>> memoCreate(@RequestBody MemoRequestDto request) {
        Memo memo = memoService.createMemo(request);
        MemoResponseDto response = new MemoResponseDto(memo);
        return ResponseEntity.ok()
                .body(CommonResponse.<MemoResponseDto>builder()
                        .statusCode(200)
                        .msg("메모 생성이 완료되었습니다.")
                        .data(response)
                        .build());
    }
}